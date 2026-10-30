/**
 * DRAFT legal texts. Replace every [bracketed] placeholder and have them reviewed
 * before store submission. The hosted versions (public URLs) are required by
 * App Store Connect and Google Play Console.
 */
export const LEGAL_LAST_UPDATED = '[YYYY-MM-DD]';

/** Same value as TERMS_VERSION in backend/api member_service.py. Bump both when the terms change. */
export const TERMS_VERSION = '2026-10-30';

export const PRIVACY_POLICY = `Privacy Policy

Last updated: ${LEGAL_LAST_UPDATED}

[Company name] ("we") operates the VISHUE app (the "App"). This policy explains what information the App handles.

1. Account (optional)
You can use the App without an account. If you create one, we collect your email address. If you sign in with Google, we also receive the name, email address, and profile photo of your Google account. Account data is stored by our authentication provider, Supabase; passwords are stored only in hashed form and we never see them. We use account data only to sign you in and to provide account features such as saved looks and rewards. When you create an account we record which version of these terms you agreed to and when. You can delete your account at any time in My > Delete account; this deletes your sign-in account and agreement record. Order records are kept for the period required by law.

2. Camera (AR try-on)
If you allow camera access, video from your front camera is processed on your device to locate facial features and draw virtual makeup. Camera images are never recorded, saved, or sent to us or anyone else. To run face tracking, the App downloads the MediaPipe library and model files from Google and jsDelivr content delivery networks; these providers receive standard request information such as your IP address. You can turn camera access off at any time in the App (My > Camera) or in your device settings.

Skin analysis normally sends one explicitly captured JPEG photo to our desktop analysis server after you sign in. The server performs face detection and skin inference in memory and returns numerical results; it does not save the photo or facial crops. The photo is released after completion or cancellation. Live camera frames used for guidance are not uploaded. Authentication requests send only your access token to Supabase, not your photo. The optional on-device experiment in internal Android builds processes a temporary photo entirely on your device. The on-device experiment does not upload the photo, facial regions, or image tensors. The temporary photo is held only during analysis and is released when the analysis ends or is cancelled. The numerical analysis results, questionnaire answers, registration date, and performance measurements are stored on your device. You can explicitly share numerical performance records from the internal measurement screen; no face image is included. This experimental feature does not provide a medical diagnosis.

3. Data stored on your device
Your cart, saved shopping lists, and settings (such as language) are stored only on your device. You can delete them at any time in My > Delete all app data, or by uninstalling the App. If you sign in, your sign-in session is also kept on your device until you log out in My > Log out.

4. Search and catalog requests
When you browse products or search for tutorials, the App sends your request (for example, a search term) to our server. Our server forwards tutorial searches to the YouTube Data API and product lookups to the Naver Search API. When you are signed in, these requests include your sign-in token so our server can recognize your account. Our hosting provider may keep standard server logs (IP address, time, requested URL) for security and operations for up to [N] days.

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
VISHUE (the "App"), operated by [Company name], helps you discover K-beauty products, preview makeup virtually, and prepare shopping lists. The App does not sell products or process payments.

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
