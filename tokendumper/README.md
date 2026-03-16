# TokenDumper

Android helper app that extracts your Firebase authentication tokens for use with the pydoglog CLI.

## Why this exists

DogLog uses Google Sign-In through Firebase Authentication. There's no public API key you can just paste in. To authenticate the CLI on a headless system (no browser), you need a Firebase refresh token -- and the easiest way to get one is to sign in on an Android device and extract it.

TokenDumper is a minimal Android app that:
1. Loads a Firebase auth page configured for DogLog's Firebase project
2. Lets you sign in with your Google account
3. Displays the resulting refresh token and ID token
4. Saves them to your device's Downloads folder

## Using the prebuilt APK

1. Copy `prebuilt/token-dumper.apk` to your Android device
2. Install it (you'll need to allow installs from unknown sources)
3. Open **TokenDumper**
4. Tap **Sign In with Google** and complete the Google sign-in flow
5. Once signed in, tap **Show Tokens**
6. Long-press the **REFRESH TOKEN** box, select all, and copy it
7. On your computer, create `~/.doglog/config.json`:

```json
{
  "refresh_token": "PASTE_YOUR_REFRESH_TOKEN_HERE"
}
```

The CLI will exchange the refresh token for an ID token automatically.

Tokens are also saved to `Downloads/dogclaw_token.txt` on the device.

## Building from source

You need `apktool` and the Android SDK (specifically `apksigner` or `jarsigner`).

### 1. Build with apktool

```bash
apktool b tokendumper/ -o token-dumper-unsigned.apk
```

### 2. Create a signing key (if you don't have one)

```bash
keytool -genkeypair -v -keystore debug.keystore -alias debug \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass android -keypass android \
  -dname "CN=Debug"
```

### 3. Align and sign

```bash
zipalign -v 4 token-dumper-unsigned.apk token-dumper-aligned.apk

apksigner sign --ks debug.keystore --ks-key-alias debug \
  --ks-pass pass:android --key-pass pass:android \
  --out token-dumper.apk token-dumper-aligned.apk
```

Or with `jarsigner`:

```bash
jarsigner -verbose -sigalg SHA256withRSA -digestalg SHA-256 \
  -keystore debug.keystore token-dumper-unsigned.apk debug

zipalign -v 4 token-dumper-unsigned.apk token-dumper.apk
```

## Source structure

```
AndroidManifest.xml                          - App manifest
src/com/dogclaw/tokendumper/MainActivity.java - WebView + JS bridge
res/layout/activity_main.xml                 - Layout with WebView
res/values/strings.xml                       - App name string
assets/signin.html                           - Firebase auth page
```

## How it works

The app loads `signin.html` in a WebView, pretending to be DogLog's Firebase hosting domain (`doglog-18366.firebaseapp.com`). This lets Firebase's `signInWithRedirect` work correctly. After Google sign-in completes, the JavaScript calls `user.getIdToken()` to get the tokens and passes them to the native Android layer via a `@JavascriptInterface` bridge.

## Security notes

- The tokens grant access to **your** DogLog account. Treat them like passwords.
- The refresh token is long-lived. Rotate it by signing out and back in.
- The APK is self-signed and will trigger "unknown source" warnings. This is expected.
