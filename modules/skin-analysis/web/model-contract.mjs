export const SKIN_TYPES = ['dry', 'balanced', 'oily'];
const INDICATORS = ['pore', 'pigmentation', 'wrinkle', 'skinType'];

export function validateModelManifest(manifest) {
  const v41 = manifest?.schema === 'skin-analysis-assets-v4.1';
  if (!['skin-analysis-assets-v3', 'skin-analysis-assets-v4', 'skin-analysis-assets-v4.1'].includes(manifest?.schema) || manifest.precision !== 'float32' ||
      manifest.preprocessing !== 'skin-preprocessing-v3' || !/^[a-f0-9]{64}$/.test(manifest.bundleVersion) ||
      manifest.roiMethod !== 'opencv_haar_facebox_proportions_v1' || manifest.models?.length !== (v41 ? 5 : 4) ||
      new Set(manifest.models.map(model => model.indicator)).size !== (v41 ? 5 : 4) ||
      (v41 && !manifest.models.some(model => model.indicator === 'acne')) ||
      !INDICATORS.every(indicator => manifest.models.some(model => model.indicator === indicator))) throw new Error('model');
  for (const model of manifest.models) {
    if (v41 && model.indicator === 'acne') {
      if (model.sha256 !== manifest.assets?.[model.file] || !/^[a-f0-9]{64}$/.test(model.sourceSha256) ||
          model.input !== 'image' || model.output !== 'score' || JSON.stringify(model.inputShape) !== '[1,3,224,224]' ||
          model.outputs !== 1 || model.decoder !== 'ldl_score' || model.threshold !== .5 ||
          model.preprocessing !== 'full-rgb-pillow-bilinear-256-224-v1' || !manifest.assets[model.fixture] ||
          !Array.isArray(model.expectedLogits) || model.expectedLogits.length !== 1 ||
          !Number.isFinite(model.expectedLogits[0]) || model.expectedLogits[0] < 0 || model.expectedLogits[0] > 1) throw new Error('model');
      continue;
    }
    if (model.sha256 !== manifest.assets?.[model.file] || !/^[a-f0-9]{64}$/.test(model.sourceSha256) ||
        model.input !== 'image' || model.output !== 'logits' || JSON.stringify(model.inputShape) !== '[1,3,256,256]' ||
        model.outputs !== (model.indicator === 'skinType' ? 3 : 1) || !manifest.assets[model.fixture] ||
        !Array.isArray(model.expectedLogits) || model.expectedLogits.length !== model.outputs ||
        model.expectedLogits.some(value => !Number.isFinite(value))) throw new Error('model');
    if (model.roiEnhancement !== 'pillow-unsharp1-75-contrast1.4-embedded' ||
        (model.indicator === 'skinType' ? model.decoder !== 'mean_softmax' || JSON.stringify(model.classes) !== JSON.stringify(SKIN_TYPES)
          : manifest.schema !== 'skin-analysis-assets-v3'
            ? model.decoder !== 'sigmoid_binary' || model.threshold !== .5
            : model.decoder !== 'sigmoid_grade' || model.maxGrade !== (model.indicator === 'wrinkle' ? 6 : 5))) throw new Error('model');
  }
}

export function decodeBinary(logit) {
  if (!Number.isFinite(logit)) throw new Error('model');
  const probability = 1 / (1 + Math.exp(-logit));
  return { label: probability >= .5 ? 1 : 0, probability };
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
