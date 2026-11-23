import { Redirect } from 'expo-router';

/** Legacy discovery links now open the home feed, where search and the product charts live. */
export default function DiscoverScreen() {
  return <Redirect href="/" />;
}
