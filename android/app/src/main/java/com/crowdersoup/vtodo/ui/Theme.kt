package com.crowdersoup.vtodo.ui

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import com.crowdersoup.vtodo.brand.Brand

private val LightColors = lightColorScheme(
    primary = Color(Brand.ACCENT),
    onPrimary = Color.White,
    background = Color(Brand.BG),
    surface = Color(Brand.BG_ELEVATED),
    onBackground = Color(Brand.TEXT),
    onSurface = Color(Brand.TEXT),
    onSurfaceVariant = Color(Brand.TEXT_SOFT),
    error = Color(Brand.DANGER),
)

private val DarkColors = darkColorScheme(
    primary = Color(Brand.DARK_ACCENT),
    onPrimary = Color(Brand.DARK_BG),
    background = Color(Brand.DARK_BG),
    surface = Color(Brand.DARK_BG_ELEVATED),
    onBackground = Color(Brand.DARK_TEXT),
    onSurface = Color(Brand.DARK_TEXT),
    onSurfaceVariant = Color(Brand.DARK_TEXT_SOFT),
    error = Color(Brand.DARK_DANGER),
)

@Composable
fun VtodoTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = if (isSystemInDarkTheme()) DarkColors else LightColors,
        content = content,
    )
}
