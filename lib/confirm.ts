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

export function offerAction(message: string, accept: string, later: string, onAccept: () => void, onLater: () => void) {
  if (Platform.OS === 'web') {
    if (window.confirm(message)) onAccept(); else onLater();
    return;
  }
  Alert.alert(message, undefined, [
    { text: later, style: 'cancel', onPress: onLater },
    { text: accept, onPress: onAccept },
  ], { cancelable: false });
}

export function notify(message: string) {
  if (Platform.OS === 'web') {
    window.alert(message);
    return;
  }
  Alert.alert(message);
}
