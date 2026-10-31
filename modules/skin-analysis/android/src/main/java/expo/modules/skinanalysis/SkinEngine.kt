package expo.modules.skinanalysis

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import android.os.Build
import android.os.Debug
import android.os.SystemClock
import org.json.JSONArray
import org.json.JSONObject
import org.opencv.android.OpenCVLoader
import org.opencv.core.Rect
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.nio.FloatBuffer
import java.security.MessageDigest
import java.util.UUID
import kotlin.math.abs
import kotlin.math.max

internal class SkinEngine(private val context: Context) {
  companion object {
    private val validated = mutableSetOf<String>()
    private val environment: OrtEnvironment by lazy { OrtEnvironment.getEnvironment() }
  }
  private val analyzingAt = SystemClock.elapsedRealtimeNanos()
  private val manifest = JSONObject(context.assets.open("skin/manifest.json").bufferedReader().use { it.readText() })
  private val assets = manifest.getJSONObject("assets")

  private fun hash(file: File): String {
    val digest = MessageDigest.getInstance("SHA-256")
    file.inputStream().use { stream ->
      val buffer = ByteArray(1024 * 1024)
      while (true) { val n = stream.read(buffer); if (n < 0) break; digest.update(buffer, 0, n) }
    }
    return digest.digest().joinToString("") { "%02x".format(it.toInt() and 255) }
  }

  private fun assetFile(name: String): File {
    require(name.matches(Regex("[a-zA-Z0-9_.-]+"))) { "Invalid asset name" }
    val expected = assets.getString(name)
    require(expected.matches(Regex("[a-f0-9]{64}")))
    val folder = File(context.filesDir, "skin-analysis-assets").also { it.mkdirs() }
    val file = File(folder, "$expected-$name")
    if (!file.exists()) {
      val temporary = File(folder, "$expected.tmp")
      try {
        context.assets.open("skin/$name").use { source -> temporary.outputStream().use { source.copyTo(it) } }
        require(hash(temporary) == expected) { "Asset hash mismatch" }
        check(temporary.renameTo(file)) { "Unable to prepare model" }
      } finally { temporary.delete() }
    }
    require(hash(file) == expected) { "Asset hash mismatch" }
    return file
  }

  private fun floats(name: String): FloatArray {
    val bytes = assetFile(name).readBytes()
    require(bytes.size == 3 * 256 * 256 * 4)
    return FloatArray(bytes.size / 4).also { ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer().get(it) }
  }

  private fun validatePreprocessing(token: Int) {
    val key = "preprocess:" + manifest.getString("bundleVersion")
    if (key in validated) return
    val fixtures = JSONArray(assetFile("fixtures.json").readText())
    for (index in 0 until fixtures.length()) {
      SkinWork.check(token)
      val fixture = fixtures.getJSONObject(index)
      val image = SkinImages.decode(assetFile(fixture.getString("image")).readBytes())
      try {
        val box = fixture.optJSONArray("bbox")
        val rect = box?.let { Rect(it.getInt(0), it.getInt(1), it.getInt(2) - it.getInt(0), it.getInt(3) - it.getInt(1)) }
        val actual = SkinImages.tensor(image, rect)
        val expected = floats(fixture.getString("tensor"))
        val tolerance = fixture.getDouble("maxAbsoluteError")
        require(actual.indices.all { abs(actual[it] - expected[it]) <= tolerance }) { "Preprocessing parity failed" }
      } finally { image.release() }
    }
    validated.add(key)
  }

  @Suppress("UNCHECKED_CAST")
  private fun run(session: OrtSession, values: FloatArray): FloatArray {
    OnnxTensor.createTensor(environment, FloatBuffer.wrap(values), longArrayOf(1, 3, 256, 256)).use { tensor ->
      session.run(mapOf("image" to tensor)).use { outputs ->
        return (outputs[0].value as Array<FloatArray>)[0].copyOf().also { logits ->
          require(logits.all { it.isFinite() }) { "Non-finite prediction" }
        }
      }
    }
  }

  fun analyze(capture: SkinCapture, firstInProcess: Boolean, progress: (String) -> Unit): Map<String, Any> {
    val token = capture.generation
    require(manifest.getString("schema") == "skin-analysis-assets-v3" &&
      manifest.getString("precision") == "float32" && manifest.getString("preprocessing") == "skin-preprocessing-v3")
    require(OpenCVLoader.initLocal()) { "OpenCV initialization failed" }
    val validationAt = SystemClock.elapsedRealtimeNanos()
    validatePreprocessing(token)
    val validationMs = SkinWork.ms(validationAt)
    val preparedAt = SystemClock.elapsedRealtimeNanos()
    val image = SkinImages.decode(capture.bytes, capture.rotation)
    val prepareMs = SkinWork.ms(preparedAt)
    try {
      val detectedAt = SystemClock.elapsedRealtimeNanos()
      val regions = SkinImages.regions(image, assetFile("face.xml").absolutePath)
      val detectionMs = SkinWork.ms(detectedAt)
      val records = manifest.getJSONArray("models")
      require(records.length() == 4)
      val features = mutableMapOf<String, Int>()
      val timings = mutableListOf<Map<String, Any>>()
      var skinType: Map<String, Any>? = null
      var memoryPss = Debug.getPss()
      for (index in 0 until records.length()) {
        SkinWork.check(token)
        val model = records.getJSONObject(index)
        val indicator = model.getString("indicator")
        require(model.getString("roiEnhancement") == "pillow-unsharp1-75-contrast1.4-embedded")
        if (indicator == "skinType") {
          require(model.getString("decoder") == "mean_softmax" &&
            model.getJSONArray("classes").toString() == "[\"dry\",\"balanced\",\"oily\"]")
        } else require(model.getString("decoder") == "sigmoid_grade" &&
          model.getInt("maxGrade") == (if (indicator == "wrinkle") 6 else 5))
        progress(indicator)
        val loadAt = SystemClock.elapsedRealtimeNanos()
        val path = assetFile(model.getString("file"))
        require(model.getString("sha256") == assets.getString(model.getString("file")))
        OrtSession.SessionOptions().use { options ->
          options.setIntraOpNumThreads(2)
          options.setInterOpNumThreads(1)
          options.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
          environment.createSession(path.absolutePath, options).use { session ->
            val loadMs = SkinWork.ms(loadAt)
            val modelValidationAt = SystemClock.elapsedRealtimeNanos()
            val validationKey = model.getString("sha256")
            if (validationKey !in validated) {
              val actual = run(session, floats(model.getString("fixture")))
              val expected = model.getJSONArray("expectedLogits")
              require(actual.size == expected.length() && actual.indices.all {
                abs(actual[it] - expected.getDouble(it)) <= 1e-4 + 1e-3 * abs(expected.getDouble(it))
              }) { "Mobile model parity failed" }
              validated.add(validationKey)
            }
            val modelValidationMs = SkinWork.ms(modelValidationAt)
            var prepMs = 0.0; var inferenceMs = 0.0
            val parts: List<Pair<String, Int>> = when (indicator) {
              "pore" -> listOf("pore_grade_cheek_image_left" to 5, "pore_grade_cheek_image_right" to 6)
              "pigmentation" -> listOf("pigmentation_grade_forehead" to 1,
                "pigmentation_grade_cheek_image_left" to 5, "pigmentation_grade_cheek_image_right" to 6)
              "wrinkle" -> listOf("wrinkle_grade_forehead" to 1, "wrinkle_grade_glabella" to 2,
                "wrinkle_grade_eye_image_left" to 3, "wrinkle_grade_eye_image_right" to 4)
              "skinType" -> listOf("forehead" to 1, "leftCheek" to 5, "rightCheek" to 6)
              else -> error("Unsupported model")
            }
            val typeLogits = mutableListOf<FloatArray>()
            for ((key, part) in parts) {
              SkinWork.check(token)
              val prepAt = SystemClock.elapsedRealtimeNanos()
              val input = SkinImages.tensor(image, regions.getValue(part))
              prepMs += SkinWork.ms(prepAt)
              val inferAt = SystemClock.elapsedRealtimeNanos()
              val logits = run(session, input)
              inferenceMs += SkinWork.ms(inferAt)
              SkinWork.check(token)
              if (indicator == "skinType") {
                require(logits.size == 3)
                typeLogits.add(logits)
              } else {
                require(logits.size == 1)
                features[key] = SkinDecoding.grade(logits[0], model.getInt("maxGrade"))
              }
              memoryPss = max(memoryPss, Debug.getPss())
            }
            if (indicator == "skinType") skinType = SkinDecoding.skinType(typeLogits)
            timings.add(mapOf("indicator" to indicator, "sourceSha256" to model.getString("sourceSha256"),
              "sha256" to model.getString("sha256"), "loadMs" to loadMs, "validationMs" to modelValidationMs,
              "preprocessingMs" to prepMs, "inferenceMs" to inferenceMs))
          }
        }
      }
      require(features.size == 9 && skinType != null && timings.map { it["indicator"] }.toSet() ==
        setOf("pore", "pigmentation", "wrinkle", "skinType"))
      SkinWork.check(token)
      val appInfo = context.packageManager.getPackageInfo(context.packageName, 0)
      val debuggable = context.applicationInfo.flags and android.content.pm.ApplicationInfo.FLAG_DEBUGGABLE != 0
      // Optional preview creation is part of the wait experienced by the user.
      val preview = try { SkinImages.preview(image, regions) } catch (_: Exception) { null }
      SkinWork.check(token)
      val total = SkinWork.ms(capture.startedNs)
      val timing = mapOf("runId" to UUID.randomUUID().toString(), "processId" to SkinWork.processId,
        "firstInProcess" to firstInProcess, "device" to "${Build.MANUFACTURER} ${Build.MODEL}",
        "androidVersion" to Build.VERSION.RELEASE, "build" to "${appInfo.versionName}:${if (debuggable) "debug" else "release"}",
        "runtime" to "onnxruntime-android:1.22.0/cpu/threads:2", "bundleVersion" to manifest.getString("bundleVersion"),
        "alignmentMs" to capture.alignmentMs, "captureMs" to capture.captureMs,
        "imagePreparationMs" to prepareMs, "validationMs" to validationMs, "detectionMs" to detectionMs,
        "nativeMs" to SkinWork.ms(analyzingAt), "totalMs" to total,
        "memoryPssKb" to memoryPss, "models" to timings)
      // The optional preview is returned only in memory and separated from the persisted result by JS.
      val result = mutableMapOf<String, Any>("schema" to "skin-analysis-mobile-v3", "features" to features,
        "skinType" to skinType!!, "preprocessing" to "skin-v3-embedded-enhancement",
        "roiMethod" to "opencv_haar_facebox_proportions_v1", "validationStatus" to "experimental_unvalidated", "timing" to timing)
      if (preview != null) result["preview"] = preview
      return result
    } finally { image.release() }
  }
}
