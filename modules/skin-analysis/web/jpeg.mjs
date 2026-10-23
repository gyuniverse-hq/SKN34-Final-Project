export function createJpegRoundTrip(module) {
  return rgb => {
    const encoder = new module.JPEGEncoder(), decoder = new module.JPEGDecoder();
    try {
      encoder.setQuality(95); encoder.setProgressive(0); encoder.setSubSampling(2);
      encoder.getDecodedBuffer({ width: 256, height: 256, bitsPerSample: 8, componentCount: 3, isSigned: false }).set(rgb);
      encoder.encode();
      const encoded = encoder.getEncodedBuffer();
      decoder.getEncodedBuffer(encoded.length).set(encoded); decoder.decode();
      return new Uint8Array(decoder.getDecodedBuffer());
    } finally { encoder.delete(); decoder.delete(); }
  };
}
