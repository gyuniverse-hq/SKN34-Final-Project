package expo.modules.skinanalysis

import org.junit.Assert.assertEquals
import org.junit.Test

class CaptureGateTest {
  private val face = FacePosition(.5f, .48f, .5f, .20f, .74f, trackingId = 1)
  @Test fun waitsForContinuousStableFace() {
    val gate = CaptureGate()
    for (at in listOf(0L, 300L, 600L, 900L, 1200L)) {
      assertEquals("hold", gate.update(listOf(face), at).guidance)
    }
    assertEquals(1.0, gate.update(listOf(face), 1500).progress, 0.0)
  }
  @Test fun resetsOnMissingOrMultipleFacesAndTrackingChanges() {
    val gate = CaptureGate()
    gate.update(listOf(face), 0); gate.update(listOf(face), 500)
    assertEquals("multipleFaces", gate.update(listOf(face, face), 700).guidance)
    assertEquals(0.0, gate.update(listOf(face), 1000).progress, 0.0)
    assertEquals("noFace", gate.update(emptyList(), 1200).guidance)
    gate.update(listOf(face), 1300)
    assertEquals(0.0, gate.update(listOf(face.copy(trackingId = 2)), 1500).progress, 0.0)
  }
  @Test fun requiresForeheadSpaceAndFrontalPose() {
    val gate = CaptureGate()
    assertEquals("forehead", gate.update(listOf(face.copy(headTop = .03f)), 0).guidance)
    assertEquals("straight", gate.update(listOf(face.copy(yaw = 30f)), 300).guidance)
    assertEquals("distance", gate.update(listOf(face.copy(width = .2f)), 600).guidance)
    assertEquals("center", gate.update(listOf(face.copy(cx = .2f)), 900).guidance)
  }
}
