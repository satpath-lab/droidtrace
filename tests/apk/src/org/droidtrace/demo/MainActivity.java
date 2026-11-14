package org.droidtrace.demo;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/**
 * Harmless test app. Its native library behaves like simple obfuscated malware: it keeps a
 * URL scrambled and decrypts it only at runtime.
 *
 * - Every 2 seconds it decrypts the URL in the background (so a trace always catches it).
 * - The "Reveal hidden URL" button decrypts it on demand (try it from the phone panel).
 */
public class MainActivity extends Activity {
    static { System.loadLibrary("dtdemo"); }

    static native double check(String input, int key, double weight);
    static native String revealUrl();

    private final Handler handler = new Handler();
    private int round;
    private TextView status;
    private TextView tapped;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(48, 48, 48, 48);

        Button reveal = new Button(this);
        reveal.setText("Reveal hidden URL");
        reveal.setTextSize(22);
        reveal.setOnClickListener(new View.OnClickListener() {
            public void onClick(View v) {
                tapped.setText("You tapped the button. Decrypted: " + revealUrl());
            }
        });

        status = new TextView(this);
        status.setTextSize(20);
        status.setPadding(0, 32, 0, 0);

        tapped = new TextView(this);
        tapped.setTextSize(20);
        tapped.setPadding(0, 32, 0, 0);

        root.addView(reveal);
        root.addView(tapped);
        root.addView(status);
        setContentView(root);

        handler.post(new Runnable() {
            public void run() {
                double r = check("device-id-1234", round, 2.5);
                String url = revealUrl();
                status.setText("Background round " + round + " (" + r + ")\n" + url);
                round++;
                handler.postDelayed(this, 2000);
            }
        });
    }
}
