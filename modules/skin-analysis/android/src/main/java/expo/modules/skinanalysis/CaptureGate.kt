package expo.modules.skinanalysis

import kotlin.math.abs

internal data class FacePosition(
  val cx: Float, val cy: Float, val width: Float, val headTop: Float, val bottom: Float,
  val pitch: Float = 0f, val yaw: Float = 0f, val roll: Float = 0f, val trackingId: Int? = null
)
internal data class CaptureReadiness(val guidance: String, val progress: Double)

/** Coordinates are mapped to the same mirrored PreviewView as the React guide. */
internal class CaptureGate {
  private var since: Long? = null
  private var lastAt: Long? = null
  private var previous: FacePosition? = null

  fun reset() { since = null; lastAt = null; previous = null }
  fun update(faces: List<FacePosition>, now: Long): CaptureReadiness {
    val face = faces.singleOrNull()
    val guidance = when {
      faces.isEmpty() -> "noFace"
      face == null -> "multipleFaces"
      abs(face.yaw) > 12 || abs(face.roll) > 12 || abs(face.pitch) > 12 -> "straight"
      face.width < .40f || face.width > .65f -> "distance"
      abs(face.cx - .5f) > .08f || abs(face.cy - .48f) > .10f -> "center"
      face.headTop < .14f || face.headTop > .27f || face.bottom > .78f -> "forehead"
      else -> "hold"
    }
    val last = previous
    if (guidance != "hold") { reset(); return CaptureReadiness(guidance, 0.0) }
    require(face != null)
    if (last == null || abs(face.cx - last.cx) > .02f || abs(face.cy - last.cy) > .02f ||
      abs(face.width - last.width) > .03f || face.trackingId != last.trackingId ||
      lastAt?.let { now - it > 600 } == true) since = null
    if (since == null) since = now
    previous = face; lastAt = now
    return CaptureReadiness("hold", ((now - since!!) / 1500.0).coerceIn(0.0, 1.0))
  }
}
