import org.gradle.api.DefaultTask
import org.gradle.api.file.DirectoryProperty
import org.gradle.api.file.RegularFileProperty
import org.gradle.api.tasks.InputFile
import org.gradle.api.tasks.OutputDirectory
import org.gradle.api.tasks.TaskAction

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.compose)
    alias(libs.plugins.kotlin.serialization)
    alias(libs.plugins.ksp)
}

android {
    namespace = "com.crowdersoup.vtodo"
    compileSdk = 37

    defaultConfig {
        applicationId = "com.crowdersoup.vtodo"
        minSdk = 26
        targetSdk = 36
        versionCode = 4
        versionName = "0.4.0"
    }

    signingConfigs {
        getByName("debug") {
            storeFile = file("debug.keystore")
            storePassword = "android"
            keyAlias = "androiddebugkey"
            keyPassword = "android"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildFeatures {
        compose = true
    }

}

// The website owns the mark and the palette. This copies static/logo.png into the
// launcher icon and writes the color constants from static/app.css, so the app
// cannot keep a second copy that drifts.
val syncBrand = tasks.register<SyncBrandTask>("syncBrand") {
    cssFile.set(rootProject.file("../static/app.css"))
    logoFile.set(rootProject.file("../static/logo.png"))
    resDir.set(layout.buildDirectory.dir("generated/brand/res"))
    kotlinDir.set(layout.buildDirectory.dir("generated/brand/kotlin"))
}

androidComponents {
    onVariants { variant ->
        variant.sources.kotlin?.addGeneratedSourceDirectory(syncBrand, SyncBrandTask::kotlinDir)
        variant.sources.res?.addGeneratedSourceDirectory(syncBrand, SyncBrandTask::resDir)
    }
}

abstract class SyncBrandTask : DefaultTask() {
    @get:InputFile
    abstract val cssFile: RegularFileProperty

    @get:InputFile
    abstract val logoFile: RegularFileProperty

    @get:OutputDirectory
    abstract val resDir: DirectoryProperty

    @get:OutputDirectory
    abstract val kotlinDir: DirectoryProperty

    @TaskAction
    fun generate() {
        val css = cssFile.get().asFile.readText()
        fun block(marker: String): String {
            val start = css.indexOf(marker)
            if (start < 0) error("app.css has no $marker block")
            val open = css.indexOf('{', start)
            val close = css.indexOf('}', open)
            if (open < 0 || close < 0) error("app.css block $marker is not closed")
            return css.substring(open + 1, close)
        }
        fun hex(source: String, variable: String): String {
            val match = Regex("""${Regex.escape(variable)}\s*:\s*(#[0-9A-Fa-f]{6})""").find(source)
                ?: error("app.css is missing $variable")
            return match.groupValues[1].uppercase()
        }
        val light = block(":root")
        val dark = block("[data-theme=\"dark\"]")
        val pairs = listOf(
            "bg" to "--bg",
            "bg_elevated" to "--bg-elevated",
            "text" to "--text",
            "text_soft" to "--text-soft",
            "accent" to "--accent",
            "danger" to "--danger",
        )
        val colors = pairs.map { (key, variable) -> key to hex(light, variable) } +
            pairs.map { (key, variable) -> "dark_$key" to hex(dark, variable) }

        val res = resDir.get().asFile
        val drawable = res.resolve("drawable-nodpi")
        drawable.mkdirs()
        logoFile.get().asFile.copyTo(drawable.resolve("ic_brand_logo.png"), overwrite = true)
        val values = res.resolve("values")
        values.mkdirs()
        values.resolve("brand_colors.xml").writeText(
            buildString {
                appendLine("""<?xml version="1.0" encoding="utf-8"?>""")
                appendLine("<resources>")
                colors.forEach { (name, value) ->
                    appendLine("""    <color name="brand_$name">$value</color>""")
                }
                appendLine("</resources>")
            },
        )

        val packageDir = kotlinDir.get().asFile.resolve("com/crowdersoup/vtodo/brand")
        packageDir.mkdirs()
        packageDir.resolve("Brand.kt").writeText(
            buildString {
                appendLine("package com.crowdersoup.vtodo.brand")
                appendLine()
                appendLine("// Generated from static/app.css by syncBrand. Do not edit.")
                appendLine("object Brand {")
                colors.forEach { (name, value) ->
                    appendLine("    const val ${name.uppercase()} = 0xFF${value.removePrefix("#")}L")
                }
                appendLine("}")
            },
        )
    }
}

kotlin {
    compilerOptions {
        jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.lifecycle.runtime.compose)
    implementation(libs.androidx.lifecycle.viewmodel.compose)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    implementation(libs.androidx.glance.appwidget)
    implementation(libs.androidx.room.runtime)
    implementation(libs.androidx.room.ktx)
    ksp(libs.androidx.room.compiler)
    implementation(libs.androidx.work.runtime.ktx)
    implementation(libs.androidx.security.crypto)
    implementation(libs.androidx.credentials)
    implementation(libs.androidx.credentials.play.services)
    implementation(libs.google.id)
    implementation(libs.okhttp)
    implementation(libs.kotlinx.serialization.json)
    implementation(libs.kotlinx.coroutines.android)

    testImplementation(libs.junit)
    debugImplementation(libs.androidx.compose.ui.tooling)
}
