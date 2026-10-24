package expo.modules.skinanalysis

import android.content.Context
import android.graphics.ImageFormat
import android.os.SystemClock
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageCapture
import androidx.camera.core.ImageCaptureException
import androidx.camera.core.ImageProxy
import androidx.camera.mlkit.vision.MlKitAnalyzer
import androidx.camera.view.CameraController
import androidx.camera.view.LifecycleCameraController
import androidx.camera.view.PreviewView
import androidx.core.content.ContextCompat
import androidx.lifecycle.findViewTreeLifecycleOwner
import com.google.mlkit.vision.face.Face
import com.google.mlkit.vision.face.FaceDetection
import com.google.mlkit.vision.face.FaceDetectorOptions
import expo.modules.kotlin.AppContext
import expo.modules.kotlin.viewevent.EventDispatcher
import expo.modules.kotlin.views.ExpoView

class SkinCameraView(context: Context, appContext: AppContext) : ExpoView(context, appContext) {
  override val shouldUseAndroidLayout = true
  private val onCaptureState by EventDispatcher<Map<String, Any?>>()
  private val preview = PreviewView(context)
  private val main = ContextCompat.getMainExecutor(context)
  private var controller: LifecycleCameraController? = null
  private var detector: com.google.mlkit.vision.face.FaceDetector? = null
  private var active = false
  private var captured = false
  private val gate = CaptureGate()
  private var openedAt = 0L

  init {
    preview.implementationMode = PreviewView.ImplementationMode.COMPATIBLE
    preview.scaleType = PreviewView.ScaleType.FILL_CENTER
    addView(preview, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
  }

  fun setActive(value: Boolean) {
    active = value
    if (value && isAttachedToWindow) post { start() } else if (!value) stop()
  }
  override fun onAttachedToWindow() { super.onAttachedToWindow(); if (active) post { start() } }
  override fun onDetachedFromWindow() { stop(); super.onDetachedFromWindow() }

  private fun emit(guidance: String, progress: Double = 0.0, id: String? = null) {
    onCaptureState(mapOf("guidance" to guidance, "progress" to progress, "captureId" to id))
  }

  private fun start() {
    if (!active || controller != null || !isAttachedToWindow) return
    val owner = findViewTreeLifecycleOwner() ?: return emit("cameraError")
    try {
      captured = false; gate.reset()
      openedAt = SystemClock.elapsedRealtimeNanos()
      val faceDetector = FaceDetection.getClient(FaceDetectorOptions.Builder()
        .setPerformanceMode(FaceDetectorOptions.PERFORMANCE_MODE_FAST)
        .setLandmarkMode(FaceDetectorOptions.LANDMARK_MODE_ALL)
        .enableTracking().build())
      detector = faceDetector
      val camera = LifecycleCameraController(context)
      camera.cameraSelector = CameraSelector.DEFAULT_FRONT_CAMERA
      camera.setEnabledUseCases(CameraController.IMAGE_ANALYSIS or CameraController.IMAGE_CAPTURE)
      camera.imageAnalysisTargetSize = CameraController.OutputSize(Size(640, 480))
      camera.imageCaptureTargetSize = CameraController.OutputSize(Size(1280, 960))
      camera.imageAnalysisBackpressureStrategy = ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST
      camera.setImageAnalysisAnalyzer(main, MlKitAnalyzer(listOf(faceDetector),
        ImageAnalysis.COORDINATE_SYSTEM_VIEW_REFERENCED, main) { result ->
        if (!active || captured) return@MlKitAnalyzer
        val faces = result.getValue(faceDetector)
        if (faces == null) { gate.reset(); emit("cameraError") }
        else update(faces)
      })
      controller = camera
      preview.controller = camera
      camera.bindToLifecycle(owner)
    } catch (_: Exception) { stop(); emit("cameraError") }
  }

  private fun update(faces: List<Face>) {
    if (width == 0 || height == 0) return
    val positions = faces.map { face ->
      val box = face.boundingBox
      FacePosition(box.exactCenterX() / width, box.exactCenterY() / height,
        box.width().toFloat() / width, (box.top - box.height() * .08f) / height,
        box.bottom.toFloat() / height, face.headEulerAngleX, face.headEulerAngleY, face.headEulerAngleZ, face.trackingId)
    }
    val readiness = gate.update(positions, SystemClock.elapsedRealtime())
    emit(readiness.guidance, readiness.progress)
    if (readiness.progress >= 1.0) capture()
  }

  private fun capture() {
    val camera = controller ?: return
    captured = true
    val started = SystemClock.elapsedRealtimeNanos()
    val token = SkinWork.generation.get()
    emit("capturing", 1.0)
    camera.takePicture(main, object : ImageCapture.OnImageCapturedCallback() {
      override fun onCaptureSuccess(image: ImageProxy) {
        try {
          SkinWork.check(token)
          require(image.format == ImageFormat.JPEG) { "JPEG capture required" }
          val buffer = image.planes[0].buffer
          val bytes = ByteArray(buffer.remaining()); buffer.get(bytes)
          val id = SkinWork.put(SkinCapture(bytes, image.imageInfo.rotationDegrees, started,
            SkinWork.ms(started), (started - openedAt) / 1_000_000.0, token))
          emit("capturing", 1.0, id)
        } catch (_: Exception) { if (active && token == SkinWork.generation.get()) emit("cameraError") }
        finally { image.close(); stop() }
      }
      override fun onError(exception: ImageCaptureException) { if (active) emit("cameraError"); stop() }
    })
  }

  private fun stop() {
    controller?.clearImageAnalysisAnalyzer()
    controller?.unbind()
    controller = null
    preview.controller = null
    detector?.close(); detector = null
    gate.reset()
  }
}
