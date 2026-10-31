package expo.modules.skinanalysis

import android.graphics.Bitmap
import android.util.Base64
import com.google.android.gms.tasks.Tasks
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.face.FaceContour
import com.google.mlkit.vision.face.FaceDetection
import com.google.mlkit.vision.face.FaceDetectorOptions
import org.opencv.android.Utils
import org.opencv.core.Core
import org.opencv.core.Mat
import org.opencv.core.MatOfByte
import org.opencv.core.MatOfRect
import org.opencv.core.Rect
import org.opencv.core.Size
import org.opencv.imgcodecs.Imgcodecs
import org.opencv.imgproc.Imgproc
import org.opencv.objdetect.CascadeClassifier
import java.io.ByteArrayOutputStream
import java.util.concurrent.TimeUnit
import kotlin.math.max
import kotlin.math.min
import kotlin.math.round

internal object SkinImages {
  fun decode(bytes: ByteArray, rotation: Int = 0): Mat {
    val encoded = MatOfByte(*bytes)
    val image = try { Imgcodecs.imdecode(encoded, Imgcodecs.IMREAD_COLOR or Imgcodecs.IMREAD_IGNORE_ORIENTATION) }
      finally { encoded.release() }
    if (image.empty() || image.total() > 30_000_000) { image.release(); error("Invalid photo") }
    when ((rotation % 360 + 360) % 360) {
      90 -> Core.rotate(image, image, Core.ROTATE_90_CLOCKWISE)
      180 -> Core.rotate(image, image, Core.ROTATE_180)
      270 -> Core.rotate(image, image, Core.ROTATE_90_COUNTERCLOCKWISE)
    }
    return image
  }

  fun regions(image: Mat, cascadePath: String): Map<Int, Rect> {
    val small = Mat(); val gray = Mat(); val faces = MatOfRect()
    try {
      val scale = min(1.0, 900.0 / max(image.cols(), image.rows()))
      Imgproc.resize(image, small, Size(round(image.cols() * scale), round(image.rows() * scale)))
      Imgproc.cvtColor(small, gray, Imgproc.COLOR_BGR2GRAY)
      Imgproc.equalizeHist(gray, gray)
      val detector = CascadeClassifier(cascadePath)
      require(!detector.empty()) { "Face detector missing" }
      detector.detectMultiScale(gray, faces, 1.1, 6, 0, Size(80.0, 80.0), Size())
      val detections = faces.toArray()
      require(detections.size == 1) { "Exactly one frontal face required" }
      val face = detections[0]
      val x = face.x / scale; val y = face.y / scale
      val w = face.width / scale; val h = face.height / scale
      val proportions = mapOf(
        1 to doubleArrayOf(.22, -.08, .78, .22),
        2 to doubleArrayOf(.42, .23, .58, .39),
        3 to doubleArrayOf(.02, .28, .28, .47),
        4 to doubleArrayOf(.72, .28, .98, .47),
        5 to doubleArrayOf(.08, .48, .36, .73),
        6 to doubleArrayOf(.64, .48, .92, .73)
      )
      return proportions.mapValues { (_, p) ->
        val left = max(0, round(x + p[0] * w).toInt())
        val top = max(0, round(y + p[1] * h).toInt())
        val right = min(image.cols(), round(x + p[2] * w).toInt())
        val bottom = min(image.rows(), round(y + p[3] * h).toInt())
        require(right - left >= 4 && bottom - top >= 4) { "Face touches boundary" }
        Rect(left, top, right - left, bottom - top)
      }
    } finally { small.release(); gray.release(); faces.release() }
  }

  // Shared by inference and the preview overlay; coordinates are in the rotated input image.
  fun inputCrop(bbox: Rect, width: Int, height: Int): Rect {
    val cx = (bbox.x * 2 + bbox.width) / 2
    val cy = (bbox.y * 2 + bbox.height) / 2
    val half = max(bbox.width, bbox.height) / 2
    require(half > 0)
    val left = max(0, cx - half); val top = max(0, cy - half)
    val right = min(width, cx + half); val bottom = min(height, cy + half)
    return Rect(left, top, right - left, bottom - top)
  }

  /** Optional local-only preview. Failure leaves numeric analysis unaffected. */
  fun preview(image: Mat, regions: Map<Int, Rect>): Map<String, Any>? {
    val rgba = Mat()
    val bitmap = Bitmap.createBitmap(image.cols(), image.rows(), Bitmap.Config.ARGB_8888)
    try {
      Imgproc.cvtColor(image, rgba, Imgproc.COLOR_BGR2RGBA)
      Utils.matToBitmap(rgba, bitmap)
    } catch (error: Exception) { bitmap.recycle(); throw error }
    finally { rgba.release() }
    val detector = try { FaceDetection.getClient(FaceDetectorOptions.Builder()
      .setContourMode(FaceDetectorOptions.CONTOUR_MODE_ALL).build()) }
      catch (error: Exception) { bitmap.recycle(); throw error }
    var task: com.google.android.gms.tasks.Task<List<com.google.mlkit.vision.face.Face>>? = null
    try {
      val operation = detector.process(InputImage.fromBitmap(bitmap, 0))
      task = operation
      val faces = Tasks.await(operation, 10, TimeUnit.SECONDS)
      if (faces.size != 1) return null
      val points = faces[0].getContour(FaceContour.FACE)?.points ?: return null
      if (points.size != 36) return null
      val width = image.cols(); val height = image.rows()
      val outline = points.map { listOf(it.x.toDouble() / width, it.y.toDouble() / height) }
      if (outline.any { point -> point.any { !it.isFinite() || it < 0 || it > 1 } }) return null
      val boxes = (1..6).map { index ->
        val crop = inputCrop(regions.getValue(index), width, height)
        listOf(crop.x.toDouble() / width, crop.y.toDouble() / height,
          (crop.x + crop.width).toDouble() / width, (crop.y + crop.height).toDouble() / height)
      }
      val out = ByteArrayOutputStream()
      if (!bitmap.compress(Bitmap.CompressFormat.JPEG, 80, out) || out.size() > 3 * 1024 * 1024) return null
      return mapOf("width" to width, "height" to height, "outline" to outline, "boxes" to boxes,
        "jpeg" to Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP))
    } finally {
      // Do not recycle the bitmap while ML Kit may still be reading after a timeout.
      val pending = task
      if (pending == null || pending.isComplete) { detector.close(); bitmap.recycle() }
      else pending.addOnCompleteListener { detector.close(); bitmap.recycle() }
    }
  }

  fun tensor(image: Mat, bbox: Rect? = null): FloatArray {
    if (bbox == null) return SkinResampling.normalize(SkinResampling.resize(rgb(image), image.cols(), image.rows()))
    val bounds = inputCrop(bbox, image.cols(), image.rows())
    val crop = image.submat(bounds)
    val resized = Mat(); val encoded = MatOfByte()
    var jpeg: Mat? = null
    try {
      Imgproc.resize(crop, resized, Size(256.0, 256.0), 0.0, 0.0, Imgproc.INTER_LINEAR)
      require(Imgcodecs.imencode(".jpg", resized, encoded))
      jpeg = Imgcodecs.imdecode(encoded, Imgcodecs.IMREAD_COLOR)
      return SkinResampling.normalize(rgb(jpeg))
    } finally { crop.release(); resized.release(); encoded.release(); jpeg?.release() }
  }

  private fun rgb(image: Mat): ByteArray {
    val converted = Mat()
    try {
      Imgproc.cvtColor(image, converted, Imgproc.COLOR_BGR2RGB)
      return ByteArray((converted.total() * 3).toInt()).also { converted.get(0, 0, it) }
    } finally { converted.release() }
  }

}
