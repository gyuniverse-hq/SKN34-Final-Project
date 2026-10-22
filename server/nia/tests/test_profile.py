import unittest
from unittest.mock import patch

import cv2
import numpy as np

from server.nia.profile import FEATURES, ROI_METHOD, locate_regions, run_profile


def image_bytes():
    return cv2.imencode('.png', np.zeros((400, 300, 3), dtype=np.uint8))[1].tobytes()


def geometry():
    return dict(original_size=[300, 400], face_bbox=[20, 30, 280, 350], method=ROI_METHOD,
                training_annotation_match=False, boxes={part: [part, part, 100+part, 100+part] for part in range(9)})


class FixtureEngine:
    """No real weights: used only to exercise schema and failure handling."""
    def __init__(self, identifier, task, areas, fail=False):
        self.config = dict(id=identifier, task=task, areas=areas)
        self.fail = fail
        self.calls = []

    def load(self):
        if self.fail:
            raise ValueError('fixture checkpoint failed')

    def predict(self, raw, area, bbox, repeats, preview=True):
        self.calls.append((area, bbox))
        classification = self.config['task'].startswith('class/')
        prediction = dict(grade=2, probabilities=[0, 0, 1]) if classification else dict(value=13.5, unit='fixture unit')
        return dict(model=dict(sha256='a'*64, outputs=3 if classification else 1), prediction=prediction,
                    mode='class' if classification else 'regression', preprocessing=dict(crop=bbox))


class ProfileTests(unittest.TestCase):
    def test_complete_schema_preserves_sides_scales_and_unsupported_nulls(self):
        engines = {name: FixtureEngine(name, task, areas) for name, (task, areas) in FEATURES.items()}
        job = dict(completed=0)
        with patch('server.nia.profile.locate_regions', return_value=geometry()):
            result = run_profile(image_bytes(), engines, job)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['predicted'], 24)
        self.assertEqual(job['completed'], 24)
        ml = result['ml_input']
        self.assertEqual(len(ml['features']), 27)
        self.assertEqual(ml['features']['dryness_lips'], 2)
        self.assertEqual(ml['features']['moisture_chin'], 13.5)
        self.assertEqual(ml['provenance']['dryness_lips']['unit'], 'grade')
        self.assertEqual(ml['provenance']['dryness_lips']['grade_range'], [0, 2])
        for key in ('acne', 'oiliness', 'skin_type'):
            self.assertIsNone(ml['features'][key])
            self.assertEqual(ml['feature_status'][key], 'unsupported')
        left, right = engines['pore_grade'].calls
        self.assertNotEqual(left[1], right[1])
        self.assertEqual(engines['pigmentation_value'].calls[0][1], geometry()['boxes'][0])
        self.assertFalse(ml['training_roi_match'])
        self.assertFalse(ml['softmax_calibrated'])
        self.assertEqual(ml['validation_status'], 'experimental_unvalidated')

    def test_missing_failed_and_ambiguous_checkpoints_never_become_zero(self):
        task, areas = FEATURES['dryness']
        engines = {'bad': FixtureEngine('bad', task, areas, fail=True)}
        with patch('server.nia.profile.locate_regions', return_value=geometry()):
            report = run_profile(image_bytes(), engines, dict(completed=0))
        self.assertEqual(report['status'], 'no_results')
        self.assertIsNone(report['ml_input']['features']['dryness_lips'])
        self.assertEqual(report['ml_input']['feature_status']['dryness_lips'], 'failed')
        self.assertEqual(report['ml_input']['feature_status']['pore_grade_cheek_image_left'], 'unavailable')
        engines['other'] = FixtureEngine('other', task, areas)
        with patch('server.nia.profile.locate_regions', return_value=geometry()):
            report = run_profile(image_bytes(), engines, dict(completed=0))
        self.assertEqual(report['ml_input']['feature_status']['dryness_lips'], 'unavailable')

    def test_single_face_boxes_are_bounded_and_full_image_is_preserved(self):
        with patch('server.nia.profile.cv2.CascadeClassifier') as cascade:
            cascade.return_value.empty.return_value = False
            cascade.return_value.detectMultiScale.return_value = [[10, 10, 250, 300]]
            regions = locate_regions(image_bytes())
        self.assertEqual(regions['boxes'][0], [0, 0, 300, 400])
        for x1, y1, x2, y2 in regions['boxes'].values():
            self.assertTrue(0 <= x1 < x2 <= 300 and 0 <= y1 < y2 <= 400)

    def test_no_face_or_multiple_faces_are_rejected_before_inference(self):
        for faces, error in (([], 'No frontal face'), ([[1, 1, 90, 90], [100, 1, 90, 90]], 'Multiple faces')):
            with self.subTest(error=error), patch('server.nia.profile.cv2.CascadeClassifier') as cascade:
                cascade.return_value.empty.return_value = False
                cascade.return_value.detectMultiScale.return_value = faces
                with self.assertRaisesRegex(ValueError, error):
                    run_profile(image_bytes(), {}, dict(completed=0))


if __name__ == '__main__':
    unittest.main()
