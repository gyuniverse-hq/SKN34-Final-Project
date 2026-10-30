package expo.modules.skinanalysis

import kotlin.math.exp
import kotlin.math.floor

internal object SkinDecoding {
  fun grade(logit: Float, maximum: Int): Int {
    require(logit.isFinite() && maximum in listOf(5, 6))
    return floor(maximum / (1.0 + exp(-logit.toDouble())) + 0.5).toInt().coerceIn(0, maximum)
  }

  fun skinType(rois: List<FloatArray>): Map<String, Any> {
    require(rois.size == 3 && rois.all { it.size == 3 && it.all { value -> value.isFinite() } })
    val probabilities = DoubleArray(3)
    for (logits in rois) {
      val maximum = logits.max().toDouble()
      val weights = logits.map { exp(it.toDouble() - maximum) }
      val sum = weights.sum()
      weights.forEachIndexed { index, value -> probabilities[index] += value / sum / rois.size }
    }
    val best = probabilities.indices.maxByOrNull { probabilities[it] }!!
    return mapOf("label" to listOf("dry", "balanced", "oily")[best],
      "probabilities" to probabilities.toList(), "roiCount" to 3,
      "scoreType" to "mean_uncalibrated_softmax")
  }
}
