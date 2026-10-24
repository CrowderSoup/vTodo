package com.crowdersoup.vtodo

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.crowdersoup.vtodo.ui.AppViewModel
import com.crowdersoup.vtodo.ui.Screen
import com.crowdersoup.vtodo.ui.SignInScreen
import com.crowdersoup.vtodo.ui.TaskDetailScreen
import com.crowdersoup.vtodo.ui.TaskEditorScreen
import com.crowdersoup.vtodo.ui.TaskListScreen
import com.crowdersoup.vtodo.ui.VtodoTheme

class MainActivity : ComponentActivity() {
    private val viewModel: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        viewModel.openFromIntent(intent)
        setContent {
            VtodoTheme {
                val state by viewModel.state.collectAsStateWithLifecycle()
                Surface(modifier = Modifier.fillMaxSize()) {
                    when {
                        !state.signedIn -> SignInScreen(state, viewModel)
                        state.screen == Screen.List -> TaskListScreen(state, viewModel)
                        state.screen == Screen.Task -> TaskDetailScreen(state, viewModel)
                        else -> TaskEditorScreen(state, viewModel)
                    }
                }
            }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        viewModel.openFromIntent(intent)
    }

    companion object {
        const val ACTION_OPEN = "com.crowdersoup.vtodo.OPEN"
        const val EXTRA_TASK_ID = "task_id"
    }
}
