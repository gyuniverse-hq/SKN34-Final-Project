package expo.modules.skinanalysis

import org.junit.Assert.*
import org.junit.Test

class SkinDecodingTest {
  @Test fun regressionGradesUseSigmoidAndHalfUpRounding() {
    assertEquals(3, SkinDecoding.grade(0f, 5))
    assertEquals(3, SkinDecoding.grade(0f, 6))
    assertEquals(0, SkinDecoding.grade(-1000f, 5))
    assertEquals(6, SkinDecoding.grade(1000f, 6))
  }

  @Test fun skinTypeAveragesProbabilitiesAcrossThreeRegions() {
    val result = SkinDecoding.skinType(listOf(floatArrayOf(1000f, 1000f, 1000f),
      floatArrayOf(0f, 0f, 2f), floatArrayOf(0f, 0f, 2f)))
    assertEquals("oily", result["label"])
    assertEquals(3, result["roiCount"])
    @Suppress("UNCHECKED_CAST") val probabilities = result["probabilities"] as List<Double>
    assertEquals(1.0, probabilities.sum(), 1e-12)
    assertTrue(probabilities[2] > probabilities[0])
  }

  @Test(expected = IllegalArgumentException::class)
  fun rejectsMissingRegions() { SkinDecoding.skinType(listOf(floatArrayOf(1f, 2f, 3f))) }
}
