package com.example.museumdocentai;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Bundle;

import androidx.activity.EdgeToEdge;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.core.graphics.Insets;
import androidx.core.view.ViewCompat;
import androidx.core.view.WindowInsetsCompat;

import com.example.museumdocentai.ui.ChatUiManager;

import java.util.UUID;

/**
 * 【角色 A 负责】页面入口：只做"组装"和"事件转发"。
 *
 * 做什么：
 * 1. 组装：加载界面布局，创建 ChatUiManager（界面逻辑都在它那里）；
 * 2. 转发：把按钮点击、权限申请结果转告给 ChatUiManager；
 * 3. 权限：第一次点语音按钮时弹窗申请麦克风权限；
 * 4. 生成会话编号（多轮对话复用）。
 */
public class MainActivity extends AppCompatActivity {

    /** 录音权限的请求码：用来识别"麦克风权限申请"的回调 */
    private static final int REQUEST_RECORD_AUDIO = 1001;

    /** 界面与交互管理器 */
    private ChatUiManager uiManager;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        EdgeToEdge.enable(this);
        setContentView(R.layout.activity_main);

        // 沉浸式布局：给根布局加上系统栏的边距，内容不被状态栏/导航栏挡住
        ViewCompat.setOnApplyWindowInsetsListener(findViewById(R.id.main), (v, insets) -> {
            Insets systemBars = insets.getInsets(WindowInsetsCompat.Type.systemBars());
            v.setPadding(systemBars.left, systemBars.top, systemBars.right, systemBars.bottom);
            return insets;
        });

        // 会话编号：启动时生成一个随机串，整个对话过程复用（后端靠它记住上下文）
        String sessionId = UUID.randomUUID().toString();
        uiManager = new ChatUiManager(this, sessionId);

        // 按钮事件：转告给界面管理器处理
        findViewById(R.id.btn_send).setOnClickListener(v -> uiManager.onSendClicked());
        findViewById(R.id.btn_mic).setOnClickListener(v -> onMicClicked());
    }

    /** 点麦克风按钮：有录音权限就直接录，没有就先申请 */
    private void onMicClicked() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO)
                == PackageManager.PERMISSION_GRANTED) {
            uiManager.onMicClicked();
        } else {
            ActivityCompat.requestPermissions(this,
                    new String[]{Manifest.permission.RECORD_AUDIO},
                    REQUEST_RECORD_AUDIO);
        }
    }

    /** 权限申请的结果（用户点了弹窗之后系统回调到这里） */
    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQUEST_RECORD_AUDIO) {
            boolean granted = grantResults.length > 0
                    && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            if (granted) {
                uiManager.onMicClicked();   // 用户同意了，直接开始录音
            } else {
                uiManager.onAudioPermissionDenied();
            }
        }
    }

    /** 页面销毁：释放录音和播放资源 */
    @Override
    protected void onDestroy() {
        super.onDestroy();
        uiManager.release();
    }
}
