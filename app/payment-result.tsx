import { Redirect } from 'expo-router';

/** A cold deep link returns to checkout, which checks the saved order with the server. */
export default function PaymentResultScreen() {
  return <Redirect href="/checkout" />;
}
