import { Alert, Platform } from 'react-native';

export function confirmAction(
  message: string,
  confirmLabel: string,
  cancelLabel: string,
  onConfirm: () => void
) {
  if (Platform.OS === 'web') {
    if (window.confirm(message)) onConfirm();
    return;
  }
  Alert.alert(message, undefined, [
    { text: cancelLabel, style: 'cancel' },
    { text: confirmLabel, style: 'destructive', onPress: onConfirm },
  ]);
}

export function notify(message: string) {
  if (Platform.OS === 'web') {
    window.alert(message);
    return;
  }
  Alert.alert(message);
}
