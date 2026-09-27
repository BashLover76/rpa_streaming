plugins {
    id("com.android.application")
}

android {
    namespace = "fr.local.streamingdb"
    compileSdk = 35

    defaultConfig {
        applicationId = "fr.local.streamingdb"
        minSdk = 26
        targetSdk = 35
        versionCode = 4
        versionName = "0.4.0"
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}
