"""The exact preprocessing recipe is stored in every checkpoint."""

from torchvision import transforms as T
from torchvision.transforms import InterpolationMode

PREPROCESSING = {
    "image_size": [224, 224],
    "resize": "stretch",
    "interpolation": "bilinear",
    "antialias": True,
    "exif_transpose": True,
    "color_mode": "RGB",
    "mean": [0.485, 0.456, 0.406],
    "std": [0.229, 0.224, 0.225],
    "training_augmentation": {
        "horizontal_flip": 0.5,
        "rotation_degrees": 5,
        "brightness": 0.1,
        "contrast": 0.1,
    },
}


def make_transform(training: bool = False, recipe: dict | None = None):
    recipe = recipe or PREPROCESSING
    if recipe != PREPROCESSING:
        raise ValueError("Unsupported preprocessing recipe; refusing inconsistent inference")
    operations = [
        T.Resize(
            tuple(recipe["image_size"]), interpolation=InterpolationMode.BILINEAR, antialias=True
        )
    ]
    if training:
        operations.extend(
            [
                T.RandomHorizontalFlip(p=0.5),
                T.RandomRotation(5, interpolation=InterpolationMode.BILINEAR, fill=(124, 116, 104)),
                T.ColorJitter(brightness=0.1, contrast=0.1),
            ]
        )
    operations.extend([T.ToTensor(), T.Normalize(recipe["mean"], recipe["std"])])
    return T.Compose(operations)
