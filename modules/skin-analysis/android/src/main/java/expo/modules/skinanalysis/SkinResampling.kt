package expo.modules.skinanalysis

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

internal object SkinResampling {
  fun normalize(bytes: ByteArray): FloatArray {
    val mean = floatArrayOf(.485f, .456f, .406f)
    val std = floatArrayOf(.229f, .224f, .225f)
    return FloatArray(3 * 256 * 256) { index ->
      val channel = index / (256 * 256)
      ((bytes[(index % (256 * 256)) * 3 + channel].toInt() and 255) / 255f - mean[channel]) / std[channel]
    }
  }

  // Separable triangular resampling with scale-aware support, intermediate uint8
  // rounding and 22-bit coefficients reproduces Pillow's RGB bilinear antialiasing.
  // Android Bitmap scaling lacks this downsampling contract.
  private data class Weights(val start: Int, val coefficients: IntArray)
  private fun weights(input: Int): List<Weights> = List(256) { out ->
    val scale = input / 256.0
    val support = max(1.0, scale)
    val center = (out + .5) * scale
    val first = max(0, (center - support + .5).toInt())
    val last = min(input, (center + support + .5).toInt())
    val raw = DoubleArray(last - first) { i -> max(0.0, 1.0 - abs((first + i - center + .5) / support)) }
    val sum = raw.sum()
    Weights(first, IntArray(raw.size) { i -> (raw[i] / sum * (1 shl 22) + .5).toInt() })
  }

  fun resize(source: ByteArray, width: Int, height: Int): ByteArray {
    val horizontal = if (width == 256) source else ByteArray(height * 256 * 3).also { target ->
      val kernels = weights(width)
      for (y in 0 until height) for (x in 0 until 256) for (c in 0..2) {
        val kernel = kernels[x]
        var value = 1 shl 21
        kernel.coefficients.forEachIndexed { i, coefficient ->
          value += (source[(y * width + kernel.start + i) * 3 + c].toInt() and 255) * coefficient
        }
        target[(y * 256 + x) * 3 + c] = (value shr 22).coerceIn(0, 255).toByte()
      }
    }
    if (height == 256) return horizontal
    val kernels = weights(height)
    return ByteArray(256 * 256 * 3).also { target ->
      for (y in 0 until 256) for (x in 0 until 256) for (c in 0..2) {
        val kernel = kernels[y]
        var value = 1 shl 21
        kernel.coefficients.forEachIndexed { i, coefficient ->
          value += (horizontal[((kernel.start + i) * 256 + x) * 3 + c].toInt() and 255) * coefficient
        }
        target[(y * 256 + x) * 3 + c] = (value shr 22).coerceIn(0, 255).toByte()
      }
    }
  }
}
