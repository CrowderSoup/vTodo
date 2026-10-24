package com.crowdersoup.vtodo

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import com.crowdersoup.vtodo.ui.SignInScreen
import com.crowdersoup.vtodo.ui.TodayScreen
import com.crowdersoup.vtodo.ui.TodayViewModel
import com.crowdersoup.vtodo.ui.VtodoTheme

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            VtodoTheme {
                val viewModel: TodayViewModel = viewModel()
                val state by viewModel.state.collectAsStateWithLifecycle()
                Surface(modifier = Modifier.fillMaxSize()) {
                    if (state.signedIn) {
                        TodayScreen(state, viewModel)
                    } else {
                        SignInScreen(state, viewModel)
                    }
                }
            }
        }
    }
}
