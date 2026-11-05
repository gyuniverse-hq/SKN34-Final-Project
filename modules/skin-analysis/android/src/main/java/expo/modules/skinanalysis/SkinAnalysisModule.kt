package expo.modules.skinanalysis

import android.os.SystemClock
import expo.modules.kotlin.Promise
import expo.modules.kotlin.modules.Module
import expo.modules.kotlin.modules.ModuleDefinition
import java.util.UUID
import java.util.concurrent.Executors
import java.util.concurrent.atomic.AtomicInteger

internal data class SkinCapture(
  val bytes: ByteArray, val rotation: Int, val startedNs: Long,
  val captureMs: Double, val alignmentMs: Double, val generation: Int
)

internal object SkinWork {
  val generation = AtomicInteger(0)
  val executor = Executors.newSingleThreadExecutor()
  val processId = UUID.randomUUID().toString()
  private val captures = mutableMapOf<String, SkinCapture>()
  var attempts = 0
  @Synchronized fun put(capture: SkinCapture): String {
    require(capture.generation == generation.get()) { "Cancelled" }
    captures.clear()
    val id = UUID.randomUUID().toString()
    captures[id] = capture
    return id
  }
  @Synchronized fun take(id: String): SkinCapture = captures.remove(id) ?: error("Expired capture")
  @Synchronized fun cancel() { generation.incrementAndGet(); captures.clear() }
  fun check(token: Int) { check(token == generation.get()) { "Cancelled" } }
  fun ms(since: Long) = (SystemClock.elapsedRealtimeNanos() - since) / 1_000_000.0
}

class SkinAnalysisModule : Module() {
  override fun definition() = ModuleDefinition {
    Name("SkinAnalysis")
    Events("onProgress")
    View(SkinCameraView::class) {
      Events("onCaptureState")
      Prop("active") { view: SkinCameraView, active: Boolean -> view.setActive(active) }
    }
    AsyncFunction("cancelAsync") { SkinWork.cancel() }
    AsyncFunction("analyzeAsync") { captureId: String, promise: Promise ->
      val context = appContext.reactContext ?: throw IllegalStateException("No activity")
      SkinWork.executor.execute {
        try {
          val capture = SkinWork.take(captureId)
          SkinWork.check(capture.generation)
          val first = SkinWork.attempts++ == 0
          val result = SkinEngine(context).analyze(capture, first) { indicator ->
            sendEvent("onProgress", mapOf("indicator" to indicator))
          }
          SkinWork.check(capture.generation)
          promise.resolve(result)
        } catch (error: Exception) {
          // No pixels, paths, face values or exception details are logged or bridged.
          val code = when (error.message) {
            "Preprocessing parity failed", "Mobile model parity failed", "Asset hash mismatch",
            "OpenCV initialization failed", "Face detector missing", "Unable to prepare model" -> "ERR_SKIN_MODEL"
            "Exactly one frontal face required", "Face touches boundary", "Invalid photo" -> "ERR_SKIN_PHOTO"
            "Cancelled", "Expired capture" -> "ERR_SKIN_CANCELLED"
            else -> "ERR_SKIN_ANALYSIS"
          }
          promise.reject(code, code, null)
        }
      }
    }
    OnDestroy { SkinWork.cancel() }
  }
}
