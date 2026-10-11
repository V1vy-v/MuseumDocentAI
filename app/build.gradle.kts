plugins {
    alias(libs.plugins.android.application)
}

android {
    namespace = "com.example.museumdocentai"
    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "com.example.museumdocentai"
        minSdk = 24
        targetSdk = 37
        versionCode = 1
        versionName = "1.0"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            optimization {
                enable = true
                packageScope = setOf("androidx.**", "kotlin.**", "kotlinx.**")
            }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
}

dependencies {
    implementation(libs.activity.ktx)
    implementation(libs.appcompat)
    implementation(libs.constraintlayout)
    implementation(libs.material)
    // 【角色A】对接后端 API 用的网络库，开始写网络代码时取消注释：
    // implementation("com.squareup.retrofit2:retrofit:2.11.0")
    // implementation("com.squareup.retrofit2:converter-gson:2.11.0")
    // implementation("com.squareup.okhttp3:okhttp:4.12.0")
    testImplementation(libs.junit)
    androidTestImplementation(libs.espresso.core)
    androidTestImplementation(libs.ext.junit)
}