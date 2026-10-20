/**
 * DRAFT legal texts. Replace every [bracketed] placeholder and have them reviewed
 * before store submission. The hosted versions (public URLs) are required by
 * App Store Connect and Google Play Console.
 */
export const LEGAL_LAST_UPDATED = '[YYYY-MM-DD]';

export const PRIVACY_POLICY = `Privacy Policy

Last updated: ${LEGAL_LAST_UPDATED}

[Company name] ("we") operates the K-Beauty AR app (the "App"). This policy explains what information the App handles.

1. No account, minimal data
The App does not require an account and we do not collect your name, email address, or phone number.

2. Camera (AR try-on)
If you allow camera access, video from your front camera is processed on your device to locate facial features and draw virtual makeup. Camera images are never recorded, saved, or sent to us or anyone else. To run face tracking, the App downloads the MediaPipe library and model files from Google and jsDelivr content delivery networks; these providers receive standard request information such as your IP address. You can turn camera access off at any time in the App (My > Camera) or in your device settings.

3. Data stored on your device
Your cart, saved shopping lists, and settings (such as language) are stored only on your device. You can delete them at any time in My > Delete all app data, or by uninstalling the App.

4. Search and catalog requests
When you browse products or search for tutorials, the App sends your request (for example, a search term) to our server. Our server forwards tutorial searches to the YouTube Data API and product lookups to the Naver Search API. Our hosting provider may keep standard server logs (IP address, time, requested URL) for security and operations for up to [N] days.

5. YouTube API Services
The App uses YouTube API Services. By using tutorial features you agree to the YouTube Terms of Service (https://www.youtube.com/t/terms). Google's Privacy Policy applies to YouTube content: https://policies.google.com/privacy

6. External links
Links to online sellers, maps, and YouTube open third-party services that have their own privacy policies.

7. Children
The App is not directed to children under 14.

8. Your rights and contact
For questions or requests about your information, contact us at [contact email].

9. Changes
We will post updates to this policy in the App and at [privacy policy URL].`;

export const TERMS_OF_USE = `Terms of Use

Last updated: ${LEGAL_LAST_UPDATED}

1. The service
K-Beauty AR (the "App"), operated by [Company name], helps you discover K-beauty products, preview makeup virtually, and prepare shopping lists. The App does not sell products or process payments.

2. Virtual try-on
AR previews are simulations. Actual color, texture, and results vary with lighting, device screen, and skin. Always check products in person or with the seller before buying.

3. Product information and prices
Product details and prices are provided for reference and may change. Final prices and availability are set by stores and sellers. Purchases made through external links are agreements between you and that seller.

4. Looks and third-party content
Curated looks are inspired by public makeup trends and do not imply endorsement by any artist, brand, or store. Tutorial videos are provided by YouTube and are subject to the YouTube Terms of Service (https://www.youtube.com/t/terms).

5. Acceptable use
Do not misuse the App, interfere with its servers, or attempt to access it by automated means.

6. Disclaimer and liability
The App is provided "as is". To the extent permitted by law, [Company name] is not liable for indirect or consequential damages arising from use of the App.

7. Contact
[contact email]`;
