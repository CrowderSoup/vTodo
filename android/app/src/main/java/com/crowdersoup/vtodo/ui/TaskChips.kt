package com.crowdersoup.vtodo.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.crowdersoup.vtodo.today.statusColorArgb

@Composable
fun StatusChip(
    name: String,
    colorHex: String,
    selected: Boolean,
    onClick: (() -> Unit)? = null,
) {
    val tint = statusColorArgb(colorHex)?.let(::Color) ?: MaterialTheme.colorScheme.primary
    val background = if (selected) tint.copy(alpha = 0.16f) else Color.Transparent
    val border = if (selected) tint.copy(alpha = 0.0f) else MaterialTheme.colorScheme.outline.copy(alpha = 0.5f)
    Row(
        modifier = Modifier
            .clip(CircleShape)
            .background(background)
            .border(1.dp, border, CircleShape)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 10.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Box(
            modifier = Modifier
                .size(8.dp)
                .clip(CircleShape)
                .background(tint),
        )
        Text(
            text = name,
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurface,
        )
    }
}

@Composable
fun TagChip(text: String, onClick: (() -> Unit)? = null) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelLarge,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
        modifier = Modifier
            .clip(CircleShape)
            .background(MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.7f))
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 10.dp, vertical = 6.dp),
    )
}

@Composable
fun MetaChip(text: String, danger: Boolean = false) {
    val color = if (danger) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant
    Text(
        text = text,
        style = MaterialTheme.typography.labelLarge,
        color = color,
        modifier = Modifier
            .clip(RoundedCornerShape(999.dp))
            .background(
                if (danger) {
                    MaterialTheme.colorScheme.error.copy(alpha = 0.12f)
                } else {
                    MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.7f)
                },
            )
            .padding(horizontal = 10.dp, vertical = 6.dp),
    )
}
