export const SKIN_TYPES = ['dry', 'balanced', 'oily'];
const INDICATORS = ['acne', 'pore', 'pigmentation', 'wrinkle', 'skinType'];

export function validateModelManifest(manifest) {
  if (manifest?.schema !== 'skin-analysis-assets-v2' || manifest.precision !== 'float32' ||
      manifest.preprocessing !== 'skin-preprocessing-v3' || !/^[a-f0-9]{64}$/.test(manifest.bundleVersion) ||
      manifest.roiMethod !== 'opencv_haar_facebox_proportions_v1' || manifest.models?.length !== 5 ||
      new Set(manifest.models.map(model => model.indicator)).size !== 5 ||
      !INDICATORS.every(indicator => manifest.models.some(model => model.indicator === indicator))) throw new Error('model');
  for (const model of manifest.models) {
    if (model.sha256 !== manifest.assets?.[model.file] || !/^[a-f0-9]{64}$/.test(model.sourceSha256) ||
        model.input !== 'image' || model.output !== 'logits' || JSON.stringify(model.inputShape) !== '[1,3,256,256]' ||
        model.outputs !== (model.indicator === 'skinType' ? 3 : 1) || !manifest.assets[model.fixture] ||
        !Array.isArray(model.expectedLogits) || model.expectedLogits.length !== model.outputs ||
        model.expectedLogits.some(value => !Number.isFinite(value))) throw new Error('model');
    if (model.indicator === 'acne') {
      if (!(model.threshold > 0 && model.threshold < 1)) throw new Error('model');
    } else if (model.roiEnhancement !== 'pillow-unsharp1-75-contrast1.4-embedded' ||
        (model.indicator === 'skinType' ? model.decoder !== 'mean_softmax' || JSON.stringify(model.classes) !== JSON.stringify(SKIN_TYPES)
          : model.decoder !== 'sigmoid_grade' || model.maxGrade !== (model.indicator === 'wrinkle' ? 6 : 5))) throw new Error('model');
  }
}

export function decodeGrade(logit, maximum) {
  if (!Number.isFinite(logit) || ![5, 6].includes(maximum)) throw new Error('model');
  return Math.max(0, Math.min(maximum, Math.floor(maximum / (1 + Math.exp(-logit)) + .5)));
}

export function meanSkinType(rois) {
  if (rois.length !== 3 || rois.some(values => values.length !== 3 || values.some(value => !Number.isFinite(value)))) throw new Error('model');
  const probabilities = [0, 0, 0];
  for (const values of rois) {
    const maximum = Math.max(...values), weights = Array.from(values, value => Math.exp(value - maximum));
    const sum = weights.reduce((a, b) => a + b, 0);
    weights.forEach((value, i) => { probabilities[i] += value / sum / rois.length; });
  }
  const best = probabilities.reduce((at, value, i) => value > probabilities[at] ? i : at, 0);
  return { label: SKIN_TYPES[best], probabilities, roiCount: 3, scoreType: 'mean_uncalibrated_softmax' };
}
