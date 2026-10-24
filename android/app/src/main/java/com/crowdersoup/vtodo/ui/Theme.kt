package com.crowdersoup.vtodo.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

private val Teal = Color(0xFF0F766E)
private val Ink = Color(0xFF1D2630)
private val Paper = Color(0xFFF2EDE6)
private val Card = Color(0xFFFBF7F1)
private val Danger = Color(0xFFBB4D3E)

private val LightColors = lightColorScheme(
    primary = Teal,
    onPrimary = Color.White,
    background = Paper,
    surface = Card,
    onBackground = Ink,
    onSurface = Ink,
    error = Danger,
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFF38B2AC),
    onPrimary = Color(0xFF11161D),
    background = Color(0xFF11161D),
    surface = Color(0xFF161C25),
    onBackground = Color(0xFFEDF2F7),
    onSurface = Color(0xFFEDF2F7),
    error = Color(0xFFFC8181),
)

@Composable
fun VtodoTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) DarkColors else LightColors,
        content = content,
    )
}
