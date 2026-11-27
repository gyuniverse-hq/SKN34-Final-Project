import type { ImagePickerAsset } from 'expo-image-picker';
import { prepareCommunityPhoto } from '@/lib/lookCommunityPhoto';

const mockManipulate = jest.fn();
const mockSize = jest.fn();

jest.mock('expo-file-system', () => ({
  File: class {
    size: number;
    constructor(uri: string) {
      this.size = mockSize(uri);
    }
  },
}));
jest.mock('expo-image-manipulator', () => ({
  ImageManipulator: { manipulate: (uri: string) => mockManipulate(uri) },
  SaveFormat: { JPEG: 'jpeg' },
}));

test('resizes an oversize portrait and uses the resulting JPEG for upload', async () => {
  const photo: ImagePickerAsset = {
    uri: 'file:///portrait.heic', width: 2160, height: 3000, mimeType: 'image/heic', fileSize: 5_000_000,
  };
  const resize = jest.fn();
  const saveAsync = jest.fn().mockResolvedValue({ uri: 'file:///prepared.jpg', width: 922, height: 1280 });
  mockManipulate.mockReturnValue({ resize, renderAsync: async () => ({ saveAsync }) });
  mockSize.mockReturnValue(310_000);

  expect(await prepareCommunityPhoto(photo)).toMatchObject({
    uri: 'file:///prepared.jpg', mimeType: 'image/jpeg', fileSize: 310_000,
  });
  expect(mockManipulate).toHaveBeenCalledWith(photo.uri);
  expect(resize).toHaveBeenCalledWith({ height: 1280 });
  expect(saveAsync).toHaveBeenCalledWith({ format: 'jpeg', compress: 0.82 });
});
