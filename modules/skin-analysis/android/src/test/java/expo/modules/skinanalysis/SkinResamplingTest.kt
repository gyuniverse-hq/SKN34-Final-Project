package expo.modules.skinanalysis

import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import javax.imageio.ImageIO
import kotlin.math.abs
import org.junit.Assert.assertTrue
import org.junit.Test

class SkinResamplingTest {
  @Test fun matchesPythonTensorsForIdentityDownsamplingAndUpsampling() {
    val assets = File(System.getProperty("skin.assets") ?: "src/main/assets/skin")
    for (name in listOf("identity", "downsample", "upsample")) {
      val image = ImageIO.read(File(assets, "$name.png"))
      val rgb = ByteArray(image.width * image.height * 3)
      for (y in 0 until image.height) for (x in 0 until image.width) {
        val color = image.getRGB(x, y)
        val at = (y * image.width + x) * 3
        rgb[at] = (color shr 16).toByte(); rgb[at + 1] = (color shr 8).toByte(); rgb[at + 2] = color.toByte()
      }
      val actual = SkinResampling.normalize(SkinResampling.resize(rgb, image.width, image.height))
      val bytes = File(assets, "$name.f32").readBytes()
      val expected = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asFloatBuffer()
      var error = 0.0
      for (at in actual.indices) error = maxOf(error, abs(actual[at] - expected.get(at)).toDouble())
      assertTrue("$name preprocessing mismatch: $error", error <= 1e-5)
    }
  }
}
