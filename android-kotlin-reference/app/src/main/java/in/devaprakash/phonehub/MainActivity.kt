package `in`.devaprakash.phonehub

import android.content.Context
import android.content.Intent
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.core.content.ContextCompat
import `in`.devaprakash.phonehub.net.Connection
import `in`.devaprakash.phonehub.service.HubService
import org.json.JSONObject

/**
 * Single-screen companion UI. Type the laptop IP, connect, enter the PIN the
 * laptop shows. When the laptop requests a mirror, we pop the system
 * screen-capture consent and hand the grant to HubService.
 */
class MainActivity : ComponentActivity() {
    private lateinit var conn: Connection

    // System consent for screen capture -> forward result to the service.
    private val projectionLauncher =
        registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { res ->
            if (res.resultCode == RESULT_OK && res.data != null) {
                val i = Intent(this, HubService::class.java).apply {
                    action = HubService.ACTION_MIRROR
                    putExtra(HubService.EXTRA_CODE, res.resultCode)
                    putExtra(HubService.EXTRA_DATA, res.data)
                }
                ContextCompat.startForegroundService(this, i)
            }
        }

    private fun requestProjection() {
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        projectionLauncher.launch(mpm.createScreenCaptureIntent())
    }

    private fun onControl(msg: JSONObject) {
        when (msg.optString("t")) {
            "mirror_start" -> runOnUiThread { requestProjection() }
            "mirror_stop" -> {
                startService(Intent(this, HubService::class.java)
                    .apply { action = HubService.ACTION_STOP_MIRROR })
            }
            // "clipboard","ring","sms_*" handlers wire in here next.
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent { MaterialTheme { HubScreen() } }
    }

    @OptIn(ExperimentalMaterial3Api::class)
    @Composable
    fun HubScreen() {
        var host by remember { mutableStateOf("") }
        var pin by remember { mutableStateOf("") }
        var state by remember { mutableStateOf(Connection.State.DISCONNECTED) }
        var showPin by remember { mutableStateOf(false) }

        remember {
            conn = Connection(
                ctx = this,
                onState = { s -> runOnUiThread {
                    state = s
                    if (s == Connection.State.READY) {
                        showPin = false
                        ContextCompat.startForegroundService(
                            this, Intent(this, HubService::class.java))
                    }
                } },
                onControl = { onControl(it) },
                needPin = { runOnUiThread { showPin = true } },
            )
            Hub.connection = conn
        }

        Scaffold(topBar = { TopAppBar(title = { Text("PhoneHub") }) }) { pad ->
            Column(
                Modifier.padding(pad).padding(24.dp).fillMaxSize(),
                verticalArrangement = Arrangement.spacedBy(16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                AssistChip(onClick = {}, label = { Text("Status: $state") })
                OutlinedTextField(
                    value = host, onValueChange = { host = it },
                    label = { Text("Laptop IP (e.g. 192.168.1.x)") },
                    singleLine = true, modifier = Modifier.fillMaxWidth(),
                )
                Button(
                    onClick = { if (host.isNotBlank()) conn.connect(host.trim()) },
                    modifier = Modifier.fillMaxWidth(),
                ) { Text("Connect") }

                if (showPin) {
                    OutlinedTextField(
                        value = pin, onValueChange = { pin = it },
                        label = { Text("PIN shown on the laptop") },
                        singleLine = true, modifier = Modifier.fillMaxWidth(),
                    )
                    Button(onClick = { conn.sendPin(pin.trim()) },
                        modifier = Modifier.fillMaxWidth()) { Text("Pair") }
                }
                if (state == Connection.State.READY) {
                    Text("Connected. Start a mirror from the laptop.")
                }
            }
        }
    }
}
