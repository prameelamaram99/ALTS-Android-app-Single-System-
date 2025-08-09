package com.example.altsclient_01_07_2025;

import android.os.Bundle;
import androidx.appcompat.app.AppCompatActivity;
import fi.iki.elonen.NanoHTTPD;
import android.content.Intent;
import android.util.Log;
import org.json.JSONObject;
import java.io.IOException;

public class AndroidServerActivity extends AppCompatActivity {
    private HttpServer server;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_server);

        // Start the HTTP server
        try {
            server = new HttpServer(8000);
            server.start();
            Log.d("HttpServer", "Server started on port 8000");
        } catch (IOException e) {
            Log.e("HttpServer", "Failed to start server: " + e.getMessage());
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        if (server != null) {
            server.stop();
            Log.d("HttpServer", "Server stopped");
        }
    }

    private class HttpServer extends NanoHTTPD {
        public HttpServer(int port) {
            super(port);
        }

        @Override
        public Response serve(IHTTPSession session) {
            if (session.getMethod() == Method.POST && "/get_device_status".equals(session.getUri())) {
                try {
                    // Parse request body
                    session.parseBody(new java.util.HashMap<>());
                    String body = session.getQueryParameterString();
                    JSONObject requestJson = new JSONObject(body);
                    String query = requestJson.getString("query");

                    // Simulate interaction with a smart home app
                    String status = querySmartHomeApp(query);
                    JSONObject responseJson = new JSONObject();
                    responseJson.put("status", status);

                    return newFixedLengthResponse(
                            Response.Status.OK,
                            "application/json",
                            responseJson.toString()
                    );
                } catch (Exception e) {
                    Log.e("HttpServer", "Error processing request: " + e.getMessage());
                    return newFixedLengthResponse(
                            Response.Status.INTERNAL_ERROR,
                            "application/json",
                            "{\"error\":\"" + e.getMessage() + "\"}"
                    );
                }
            }
            return newFixedLengthResponse(
                    Response.Status.NOT_FOUND,
                    "text/plain",
                    "Not found"
            );
        }

        private String querySmartHomeApp(String query) {
            // Simulate querying a smart home app via Intent
            try {
                Intent intent = new Intent("com.example.smarthome.ACTION_GET_STATUS");
                intent.putExtra("query", query);
                // Assume the smart home app responds with a broadcast or result
                // For simplicity, return a mock response
                if (query.toLowerCase().contains("lights")) {
                    return "Lights are ON";
                } else {
                    return "Unknown device status";
                }
            } catch (Exception e) {
                return "Error querying smart home app: " + e.getMessage();
            }
        }
    }
}