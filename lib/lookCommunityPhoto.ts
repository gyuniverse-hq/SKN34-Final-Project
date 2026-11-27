import { File as LocalFile } from 'expo-file-system';
import { ImageManipulator, SaveFormat } from 'expo-image-manipulator';
import type { ImagePickerAsset } from 'expo-image-picker';
import { Platform } from 'react-native';

export const COMMUNITY_PHOTO_MAX_BYTES = 2 * 1024 * 1024;

async function photoByteSize(photo: ImagePickerAsset): Promise<number> {
  if (photo.file?.size != null) return photo.file.size;
  if (photo.fileSize != null) return photo.fileSize;
  if (Platform.OS === 'web') return (await (await fetch(photo.uri)).blob()).size;
  return new LocalFile(photo.uri).size;
}

export async function prepareCommunityPhoto(photo: ImagePickerAsset): Promise<ImagePickerAsset | null> {
  let size: number | undefined;
  try {
    size = await photoByteSize(photo);
  } catch {
    // Some gallery providers don't expose the file size. Convert before uploading.
  }
  const mime = photo.mimeType ?? photo.file?.type;
  const needsConversion = mime
    ? !['image/jpeg', 'image/jpg', 'image/png', 'image/webp'].includes(mime.toLowerCase())
    : /\.(heic|heif)(?:$|[?#])/i.test(photo.fileName ?? photo.uri);
  if (size && size <= COMMUNITY_PHOTO_MAX_BYTES && !needsConversion && photo.width * photo.height <= 20_000_000) {
    return photo;
  }

  for (const [maxSide, quality] of [[1280, 0.82], [960, 0.65]]) {
    const context = ImageManipulator.manipulate(photo.uri);
    if (Math.max(photo.width, photo.height) > maxSide) {
      context.resize(photo.width >= photo.height ? { width: maxSide } : { height: maxSide });
    }
    const rendered = await context.renderAsync();
    const saved = await rendered.saveAsync({ format: SaveFormat.JPEG, compress: quality });
    const prepared = {
      ...photo, ...saved, fileName: 'look.jpg', mimeType: 'image/jpeg', fileSize: undefined, file: undefined,
    };
    const preparedSize = await photoByteSize(prepared);
    if (preparedSize > 0 && preparedSize <= COMMUNITY_PHOTO_MAX_BYTES) {
      return { ...prepared, fileSize: preparedSize };
    }
  }
  return null;
}
