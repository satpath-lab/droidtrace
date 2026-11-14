package org.droidtrace.demo;

import android.app.Activity;
import android.os.Bundle;
import android.os.Handler;
import android.widget.TextView;

/** Benign test app: calls native code that behaves like simple obfuscated malware logic. */
public class MainActivity extends Activity {
    static { System.loadLibrary("dtdemo"); }

    static native double check(String input, int key, double weight);
    static native String revealUrl();

    private final Handler handler = new Handler();
    private int round;

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        final TextView tv = new TextView(this);
        setContentView(tv);
        handler.post(new Runnable() {
            public void run() {
                double r = check("device-id-1234", round, 2.5);
                tv.setText("round " + round + " -> " + r + "\n" + revealUrl());
                if (++round < 20) handler.postDelayed(this, 1000);
            }
        });
    }
}
