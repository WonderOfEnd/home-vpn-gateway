import com.teamresourceful.resourcefulcosmetics.CosmeticsHttp;
import java.net.*;
import java.net.http.*;
import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.nio.charset.StandardCharsets;

public class TestCosmeticsTimeout {
    public static void main(String[] args) throws Exception {
        try (var server = new ServerSocket(0, 10, InetAddress.getLoopbackAddress())) {
            var executor = Executors.newSingleThreadExecutor();
            var accepted = executor.submit(() -> {
                try (var socket = server.accept()) {
                    if (args[0].equals("ok")) {
                        socket.getInputStream().read(new byte[4096]);
                        socket.getOutputStream().write("HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok".getBytes(StandardCharsets.US_ASCII));
                    } else {
                        socket.setSoTimeout(20000);
                        while (socket.getInputStream().read() != -1) {}
                    }
                }
                return null;
            });
            long start = System.nanoTime();
            try {
                var http = new CosmeticsHttp("http://127.0.0.1:" + server.getLocalPort() + "/");
                var response = args[0].equals("post")
                    ? http.post("cosmetics", Map.of(), "{}", HttpResponse.BodyHandlers.ofString())
                    : http.get("cosmetics", Map.of(), HttpResponse.BodyHandlers.ofString());
                if (!args[0].equals("ok") || response.statusCode() != 200 || !response.body().equals("ok")) {
                    throw new AssertionError("Unexpected response: " + response);
                }
                System.out.println("PASS: successful response unchanged");
            } catch (HttpTimeoutException e) {
                double seconds = (System.nanoTime() - start) / 1e9;
                if (args[0].equals("ok") || seconds < 7 || seconds > 13) throw new AssertionError("Unexpected timeout duration " + seconds, e);
                System.out.printf("PASS: %s timed out after %.2f seconds%n", args[0], seconds);
            } finally {
                executor.shutdownNow();
            }
        }
    }
}
