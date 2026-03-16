package com.dogclaw.tokendumper;

import android.app.Activity;
import android.os.Bundle;
import android.os.Environment;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;
import java.io.File;
import java.io.FileWriter;

public class MainActivity extends Activity {
    private WebView webView;
    private String htmlContent;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        htmlContent = getHtmlContent();
        webView = (WebView) findViewById(R.id.webView);
        WebSettings settings = webView.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);
        settings.setDatabaseEnabled(true);
        settings.setUserAgentString(
            "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 " +
            "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
        );

        webView.addJavascriptInterface(new AndroidBridge(), "Android");
        webView.setWebChromeClient(new WebChromeClient());
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                if (url.contains("firebaseapp.com/__/auth/handler") ||
                    url.contains("accounts.google.com") ||
                    url.contains("doglog-18366")) {
                    // Let Firebase auth URLs load normally
                    view.loadUrl(url);
                    return true;
                }
                if (url.startsWith("https://doglog-18366.firebaseapp.com") &&
                    !url.contains("/__/auth/")) {
                    // Firebase redirected back - reload our page (getRedirectResult will fire)
                    loadOurPage();
                    return true;
                }
                view.loadUrl(url);
                return true;
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                // If Firebase's auth handler finished, reload our page
                if (url != null && url.contains("firebaseapp.com/__/auth/handler")) {
                    // Give it a moment to process, then reload our page
                    view.postDelayed(new Runnable() {
                        public void run() { loadOurPage(); }
                    }, 500);
                }
            }
        });

        loadOurPage();
    }

    private void loadOurPage() {
        webView.loadDataWithBaseURL(
            "https://doglog-18366.firebaseapp.com",
            htmlContent, "text/html", "UTF-8",
            "https://doglog-18366.firebaseapp.com"  // historyUrl - key for getRedirectResult!
        );
    }

    private String getHtmlContent() {
        try {
            java.io.InputStream is = getAssets().open("signin.html");
            byte[] buf = new byte[is.available()];
            is.read(buf);
            is.close();
            return new String(buf, "UTF-8");
        } catch (final Exception e) {
            return "<html><body>Error: " + e.getMessage() + "</body></html>";
        }
    }

    class AndroidBridge {
        @JavascriptInterface
        public void saveToken(final String tokenData) {
            try {
                File file = new File(
                    Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS),
                    "dogclaw_token.txt"
                );
                FileWriter fw = new FileWriter(file);
                fw.write(tokenData);
                fw.close();
                runOnUiThread(new Runnable() {
                    public void run() {
                        Toast.makeText(MainActivity.this,
                            "Token saved!", Toast.LENGTH_LONG).show();
                    }
                });
            } catch (final Exception e) {
                runOnUiThread(new Runnable() {
                    public void run() {
                        Toast.makeText(MainActivity.this,
                            "Save error: " + e.getMessage(), Toast.LENGTH_LONG).show();
                    }
                });
            }
        }

        @JavascriptInterface
        public void log(String msg) { android.util.Log.d("DogClaw", msg); }
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }
}
