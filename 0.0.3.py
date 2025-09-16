import sys
import os
import time
import threading
import queue
import psutil
from datetime import datetime
from collections import deque

from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QGridLayout, QGroupBox, QLabel, QPushButton, QComboBox, 
                             QTableWidget, QTableWidgetItem, QListWidget, QListWidgetItem,
                             QProgressBar, QTextEdit, QCheckBox, QFileDialog, QMessageBox,
                             QHeaderView)
from PyQt6.QtCore import (Qt, pyqtSignal, pyqtSlot, QTimer)
from PyQt6.QtGui import (QColor, QCloseEvent)

import mido
from mido import MidiFile, Message

class MidiPlayerApp(QMainWindow):
    """Trusler's MIDI Player - v0.0.3(GUI Mode)"""
    
    # 信号定义
    update_status = pyqtSignal(str, str)  # 状态更新信号 (状态文本, 颜色)
    update_progress = pyqtSignal(int, int, str)  # 进度更新信号 (当前, 总时长, 时间文本)
    update_active_notes = pyqtSignal(list)  # 活跃音符更新信号
    update_performance = pyqtSignal(dict)  # 性能数据更新信号
    update_note_history = pyqtSignal(list)  # 音符历史更新信号
    update_log = pyqtSignal(str, str)  # 日志更新信号 (消息, 级别)
    update_port_status = pyqtSignal(int, bool)  # 端口状态更新信号 (端口号, 连接状态)
    update_file_list = pyqtSignal(list)  # 文件列表更新信号
    update_fps = pyqtSignal(int)  # FPS更新信号
    update_music_theory = pyqtSignal(str)  # 乐理知识更新信号
    
    def __init__(self):
        super().__init__()
        
        # 初始化配置
        self.init_config()
        
        # 初始化UI
        self.init_ui()
        
        # 初始化MIDI系统
        self.init_midi_system()
        
        # 初始化线程和队列
        self.init_threads()
        
        # 启动监控定时器
        self.start_monitors()
        
    def init_config(self):
        """初始化配置"""
        self.current_file_index = -1
        self.playlist = []
        self.is_playing = False
        self.is_paused = False
        self.playback_complete = False  # 播放完成标志
        self.current_time = 0
        self.total_time = 0
        self.active_notes = {}  # {note: {'name': '', 'octave': 0, 'frequency': 0, 'velocity': 0, 'start_time': 0}}
        self.note_history = deque(maxlen=50)
        self.message_count = 0  # 记录当前歌曲发送的MIDI消息总数
        self.session_message_count = 0  # 记录会话总消息数
        self.start_time = None
        self.queue_lengths = []
        self.average_latency = 0
        self.fps_counter = 0
        self.fps_last_time = time.time()
        self.current_tempo = 120  # 默认BPM
        self.current_time_signature = (4, 4)  # 默认拍号
        self.current_key = None  # 当前调号
        
        # 黑乐谱优化参数
        self.black_midi_mode = False
        self.num_midi_threads = 2
        self.batch_size = 10
        self.max_active_notes = 500
        self.show_active_notes = True
        
        # 端口配置
        self.port1_name = None
        self.port2_name = None
        self.port1_connected = False
        self.port2_connected = False
        self.port1_out = None
        self.port2_out = None
        
        # 线程控制
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()  # 初始为非暂停状态
        
        # 锁机制
        self.counter_lock = threading.Lock()
        
        # 实时显示属性
        self.last_display_update = time.time()
        self.last_display_count = 0
        
    def init_ui(self):
        """初始化UI界面"""
        # 设置窗口属性
        self.setWindowTitle("Trusler's MIDI Player - v0.0.3(GUI Mode)")
        self.setGeometry(100, 100, 1200, 900)
        self.setMinimumSize(900, 600)
        
        # 设置全局样式
        self.setStyleSheet(self.get_global_stylesheet())
        
        # 主中央窗口
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(15)  # 不同功能组间距
        
        # 顶部状态栏（占比 8%）
        self.create_top_status_bar(main_layout)
        
        # 文件与控制区（占比 20%）
        file_control_widget = QWidget()
        file_control_layout = QHBoxLayout(file_control_widget)
        file_control_layout.setContentsMargins(0, 0, 0, 0)
        file_control_layout.setSpacing(15)
        
        # 左侧文件管理（宽度 1:3）
        self.create_file_management_area(file_control_layout)
        
        # 右侧播放控制（宽度 3:3）
        self.create_playback_control_area(file_control_layout)
        
        main_layout.addWidget(file_control_widget)
        
        # 信息展示区（占比 45%）
        info_widget = QWidget()
        info_layout = QHBoxLayout(info_widget)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(15)
        
        # 左侧复音与性能监控（宽度 2:3）
        left_info_widget = QWidget()
        left_info_layout = QVBoxLayout(left_info_widget)
        left_info_layout.setContentsMargins(0, 0, 0, 0)
        left_info_layout.setSpacing(15)
        self.create_active_notes_area(left_info_layout)
        self.create_performance_monitor_area(left_info_layout)
        info_layout.addWidget(left_info_widget, 2)
        
        # 右侧乐理与历史（宽度 1:3）
        right_info_widget = QWidget()
        right_info_layout = QVBoxLayout(right_info_widget)
        right_info_layout.setContentsMargins(0, 0, 0, 0)
        right_info_layout.setSpacing(15)
        # 增大乐理知识区域，缩小音符历史区域
        self.create_music_theory_area(right_info_layout)
        self.create_note_history_area(right_info_layout)
        info_layout.addWidget(right_info_widget, 1)
        
        main_layout.addWidget(info_widget)
        
        # 日志区（占比 27%，固定高度 100px）
        self.create_system_log_area(main_layout)
        
        # 连接信号
        self.connect_signals()
        
    def get_global_stylesheet(self):
        """获取全局样式表 - 使用暗色主题"""
        return """
            QMainWindow {
                background-color: #1a1a1a;
                color: #ffffff;
                font-family: "Segoe UI", Arial, sans-serif;
            }
            
            QGroupBox {
                background-color: #2d2d2d;
                border: 3px solid #61c0bf;
                border-radius: 8px;
                margin-top: 15px;  /* 增加顶部margin，给标题更多空间 */
                padding: 15px;
                padding-top: 20px;  /* 增加顶部内边距 */
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 15px;
                top: -8px;  /* 调整top值，避免被覆盖 */
                background-color: #61c0bf;
                color: #1a1a1a;
                padding: 6px 12px;  /* 增加垂直padding */
                font-weight: bold;
                font-size: 12pt;
                border-radius: 4px;
                z-index: 10;  /* 确保标题在最上层 */
            }
            
            QPushButton {
                background-color: #61c0bf;
                color: #1a1a1a;
                border: none;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 11pt;
                transition: all 150ms ease-in-out;
            }
            
            QPushButton[isPlayControl="true"] {
                width: 80px;
                height: 36px;
                font-size: 12pt;
            }
            
            QPushButton:not([isPlayControl="true"]) {
                width: 90px;
                height: 32px;
            }
            
            QPushButton:hover {
                background-color: #fae3d9;
                color: #1a1a1a;
                transform: translateY(-1px);
            }
            
            QPushButton:pressed {
                background-color: #ffb6b9;
                color: #1a1a1a;
                transform: translateY(0);
            }
            
            QPushButton:disabled {
                background-color: #444444;
                color: #666666;
                transform: none;
            }
            
            QComboBox {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 2px solid #61c0bf;
                border-radius: 6px;
                padding: 8px;
                height: 32px;
                width: 160px;
                font-size: 10pt;
            }
            
            QComboBox:focus {
                border: 2px solid #ffb6b9;
                outline: none;
            }
            
            QListWidget {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 2px solid #61c0bf;
                border-radius: 8px;
                font-size: 10pt;
            }
            
            QListWidget::item:selected {
                background-color: #61c0bf;
                color: #1a1a1a;
            }
            
            QTableWidget {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 2px solid #61c0bf;
                border-radius: 8px;
                gridline-color: #444444;
                font-size: 10pt;
            }
            
            QTableWidget::header {
                background-color: #61c0bf;
                color: #1a1a1a;
                font-weight: bold;
                border-radius: 4px;
                font-size: 10pt;
            }
            
            QTableWidget::item {
                text-align: center;
                padding: 4px;
            }
            
            QProgressBar {
                background-color: #333333;
                border-radius: 10px;
                height: 20px;
                margin: 0 8px;
            }
            
            QProgressBar::chunk {
                background-color: #61c0bf;
                border-radius: 8px;
                transition: width 50ms ease-in-out;
            }
            
            QTextEdit {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 2px solid #61c0bf;
                border-radius: 8px;
                font-family: "Consolas", monospace;
                font-size: 9pt;
                padding: 8px;
            }
            
            QCheckBox {
                color: #ffffff;
                font-size: 10pt;
            }
            
            QLabel {
                color: #ffffff;
                font-size: 10pt;
            }
            
            QLabel[isTitle="true"] {
                font-weight: bold;
                font-size: 11pt;
                color: #ffffff;
            }
            
            QLabel[isStatus="true"] {
                font-size: 10pt;
                font-weight: bold;
            }
            
            QLabel[isWatermark="true"] {
                color: rgba(255, 255, 255, 0.3);
                font-size: 12px;
                font-weight: bold;
            }
            
            /* 自定义样式 */
            .status-connected {
                color: #28a745;
                font-weight: bold;
            }
            
            .status-disconnected {
                color: #dc3545;
                font-weight: bold;
            }
            
            .status-playing {
                color: #28a745;
                font-weight: bold;
            }
            
            .status-paused {
                color: #ffc107;
                font-weight: bold;
            }
            
            .status-stopped {
                color: #dc3545;
                font-weight: bold;
            }
        """
    
    def create_top_status_bar(self, parent_layout):
        """创建顶部状态栏"""
        status_widget = QWidget()
        status_layout = QHBoxLayout(status_widget)
        status_layout.setContentsMargins(8, 8, 8, 8)
        status_layout.setSpacing(15)
        
        # 水印文本 - 已恢复
        self.watermark_label = QLabel("This Program code by Trusler")
        self.watermark_label.setProperty("isWatermark", True)
        status_layout.addWidget(self.watermark_label)
        
        # 端口控制区
        port_layout = QHBoxLayout()
        port_layout.setContentsMargins(0, 0, 0, 0)
        port_layout.setSpacing(8)
        
        # 端口1
        port_layout.addWidget(QLabel("端口1:"))
        self.port1_combo = QComboBox()
        port_layout.addWidget(self.port1_combo)
        
        self.port1_btn = QPushButton("连接")
        self.port1_btn.clicked.connect(lambda: self.toggle_port_connection(1))
        port_layout.addWidget(self.port1_btn)
        
        self.port1_status = QLabel("未连接")
        self.port1_status.setProperty("isStatus", True)
        self.port1_status.setObjectName("port1_status")
        self.port1_status.setStyleSheet("color: #dc3545; font-weight: bold;")
        port_layout.addWidget(self.port1_status)
        
        # 端口2
        port_layout.addWidget(QLabel("端口2:"))
        self.port2_combo = QComboBox()
        port_layout.addWidget(self.port2_combo)
        
        self.port2_btn = QPushButton("连接")
        self.port2_btn.clicked.connect(lambda: self.toggle_port_connection(2))
        port_layout.addWidget(self.port2_btn)
        
        self.port2_status = QLabel("未连接")
        self.port2_status.setProperty("isStatus", True)
        self.port2_status.setObjectName("port2_status")
        self.port2_status.setStyleSheet("color: #dc3545; font-weight: bold;")
        port_layout.addWidget(self.port2_status)
        
        # 测试连接按钮
        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self.test_connections)
        port_layout.addWidget(self.test_btn)
        
        status_layout.addLayout(port_layout)
        
        # 全局状态提示
        self.global_status = QLabel("就绪")
        self.global_status.setProperty("isStatus", True)
        self.global_status.setStyleSheet("color: #61c0bf; font-weight: bold;")
        status_layout.addWidget(self.global_status, alignment=Qt.AlignmentFlag.AlignRight)
        
        parent_layout.addWidget(status_widget)
    
    def create_file_management_area(self, parent_layout):
        """创建文件管理区域"""
        group_box = QGroupBox("文件管理")
        layout = QVBoxLayout(group_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 文件列表
        self.file_list = QListWidget()
        self.file_list.itemDoubleClicked.connect(self.on_file_double_clicked)
        layout.addWidget(self.file_list)
        
        # 按钮组
        button_layout = QHBoxLayout()
        button_layout.setSpacing(8)
        
        self.add_btn = QPushButton("添加文件")
        self.add_btn.clicked.connect(self.add_files)
        button_layout.addWidget(self.add_btn)
        
        self.remove_btn = QPushButton("移除文件")
        self.remove_btn.clicked.connect(self.remove_file)
        button_layout.addWidget(self.remove_btn)
        
        self.clear_btn = QPushButton("清空列表")
        self.clear_btn.clicked.connect(self.clear_files)
        button_layout.addWidget(self.clear_btn)
        
        layout.addLayout(button_layout)
        
        parent_layout.addWidget(group_box, 1)
    
    def create_playback_control_area(self, parent_layout):
        """创建播放控制区域"""
        group_box = QGroupBox("播放控制")
        layout = QVBoxLayout(group_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 控制按钮
        control_layout = QHBoxLayout()
        control_layout.setSpacing(8)
        
        self.prev_btn = QPushButton("上一首")
        self.prev_btn.setProperty("isPlayControl", True)
        self.prev_btn.clicked.connect(self.play_previous)
        control_layout.addWidget(self.prev_btn)
        
        self.play_btn = QPushButton("播放")
        self.play_btn.setProperty("isPlayControl", True)
        self.play_btn.clicked.connect(self.toggle_play_pause)
        control_layout.addWidget(self.play_btn)
        
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setProperty("isPlayControl", True)
        self.stop_btn.clicked.connect(self.stop_playback)
        control_layout.addWidget(self.stop_btn)
        
        self.next_btn = QPushButton("下一首")
        self.next_btn.setProperty("isPlayControl", True)
        self.next_btn.clicked.connect(self.play_next)
        control_layout.addWidget(self.next_btn)
        
        # 音乐信息显示
        music_info_layout = QHBoxLayout()
        music_info_layout.setSpacing(15)
        music_info_layout.setContentsMargins(0, 4, 0, 4)
        
        self.bpm_label = QLabel("速度: -- BPM")
        self.bpm_label.setStyleSheet("font-weight: bold;")
        self.time_sig_label = QLabel("拍号: --/--")
        self.time_sig_label.setStyleSheet("font-weight: bold;")
        self.key_label = QLabel("调号: --")
        self.key_label.setStyleSheet("font-weight: bold;")
        
        music_info_layout.addWidget(self.bpm_label)
        music_info_layout.addWidget(self.time_sig_label)
        music_info_layout.addWidget(self.key_label)
        
        control_layout.addLayout(music_info_layout)
        
        layout.addLayout(control_layout)
        
        # 黑乐谱控制选项
        black_midi_layout = QHBoxLayout()
        black_midi_layout.setSpacing(15)
        black_midi_layout.setContentsMargins(0, 4, 0, 4)
        
        self.black_midi_check = QCheckBox("黑乐谱模式(未完成)")    #启动可能会出现逆天bug
        self.black_midi_check.setToolTip("优化黑乐谱播放性能")
        self.black_midi_check.setEnabled(False)                
        self.black_midi_check.stateChanged.connect(self.toggle_black_midi_mode)
        
        self.filter_zero_velocity_check = QCheckBox("过滤力度0音符")
        self.filter_zero_velocity_check.setToolTip("移除力度为0的音符事件")
        self.filter_zero_velocity_check.setChecked(True)
        
        self.show_active_notes_check = QCheckBox("活跃音符显示")
        self.show_active_notes_check.setToolTip("显示当前播放的音符信息")
        self.show_active_notes_check.setChecked(True)
        self.show_active_notes_check.setEnabled(False)           #依旧bug
        self.show_active_notes_check.stateChanged.connect(self.toggle_show_active_notes)
        
        black_midi_layout.addWidget(self.black_midi_check)
        black_midi_layout.addWidget(self.filter_zero_velocity_check)
        black_midi_layout.addWidget(self.show_active_notes_check)
        black_midi_layout.addStretch()
        
        layout.addLayout(black_midi_layout)
        
        # 进度条和时间显示
        progress_layout = QHBoxLayout()
        progress_layout.setSpacing(8)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 1000)
        self.progress_bar.setValue(0)
        progress_layout.addWidget(self.progress_bar, 1)
        
        self.time_label = QLabel("00:00 / 00:00")
        self.time_label.setStyleSheet("font-weight: bold; min-width: 120px; text-align: right;")
        progress_layout.addWidget(self.time_label)
        
        layout.addLayout(progress_layout)
        
        # 播放状态和性能信息
        status_layout = QHBoxLayout()
        status_layout.setSpacing(15)
        
        self.playback_status = QLabel("状态: 停止")
        self.playback_status.setProperty("isStatus", True)
        self.playback_status.setStyleSheet("color: #dc3545; font-weight: bold; font-size: 11pt;")
        
        #self.performance_info = QLabel("吞吐量: *** ev/s | 延迟: 0 ms")
        self.performance_info = QLabel("")
        self.performance_info.setStyleSheet("font-size: 9pt; color: #61c0bf;")
        
        status_layout.addWidget(self.playback_status)
        status_layout.addWidget(self.performance_info)
        status_layout.addStretch()
        
        layout.addLayout(status_layout)
        
        parent_layout.addWidget(group_box, 3)
    
    def create_active_notes_area(self, parent_layout):
        """创建活跃音符区域"""
        group_box = QGroupBox("活跃音符")
        layout = QVBoxLayout(group_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        self.active_notes_table = QTableWidget()
        self.active_notes_table.setColumnCount(5)
        self.active_notes_table.setHorizontalHeaderLabels(["音符", "八度", "频率", "力度", "时长"])
        self.active_notes_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.active_notes_table)
        
        # 浮动窗口按钮
        self.float_notes_btn = QPushButton("显示浮动音符窗口")
        self.float_notes_btn.clicked.connect(self.show_float_notes_window)
        layout.addWidget(self.float_notes_btn)
        
        parent_layout.addWidget(group_box)
    
    def create_performance_monitor_area(self, parent_layout):
        """创建性能监控区域"""
        group_box = QGroupBox("性能监控")
        layout = QGridLayout(group_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 性能监控标签样式
        label_style = "font-weight: bold; color: #ffffff;"
        value_style = "font-weight: bold; color: #61c0bf;"
        
        # 消息计数
        layout.addWidget(QLabel("消息计数:", styleSheet=label_style), 0, 0)
        self.msg_count_label = QLabel("0", styleSheet=value_style)
        layout.addWidget(self.msg_count_label, 0, 1)
        
        # 吞吐量
        layout.addWidget(QLabel("吞吐量:", styleSheet=label_style), 0, 2)
        self.throughput_label = QLabel("0 msg/s", styleSheet=value_style)
        layout.addWidget(self.throughput_label, 0, 3)
        
        # 平均延迟
        layout.addWidget(QLabel("平均延迟:", styleSheet=label_style), 1, 0)
        self.latency_label = QLabel("0 ms", styleSheet=value_style)
        layout.addWidget(self.latency_label, 1, 1)
        
        # 活跃音符
        layout.addWidget(QLabel("活跃音符:", styleSheet=label_style), 1, 2)
        self.active_count_label = QLabel("0", styleSheet=value_style)
        layout.addWidget(self.active_count_label, 1, 3)
        
        # 队列状态
        layout.addWidget(QLabel("队列状态:", styleSheet=label_style), 2, 0)
        self.queue_label = QLabel("0", styleSheet=value_style)
        layout.addWidget(self.queue_label, 2, 1)
        
        # 活跃端口
        layout.addWidget(QLabel("活跃端口:", styleSheet=label_style), 2, 2)
        self.active_ports_label = QLabel("0", styleSheet=value_style)
        layout.addWidget(self.active_ports_label, 2, 3)
        
        # FPS显示
        layout.addWidget(QLabel("FPS:", styleSheet=label_style), 2, 4)
        self.fps_label = QLabel("0", styleSheet=value_style)
        layout.addWidget(self.fps_label, 2, 5)
        
        parent_layout.addWidget(group_box)
    
    def create_music_theory_area(self, parent_layout):
        """创建乐理知识区域 - 增大尺寸"""
        group_box = QGroupBox("乐理知识")
        layout = QVBoxLayout(group_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        self.theory_text = QTextEdit()
        self.theory_text.setReadOnly(True)
        self.theory_text.setPlainText("等待音符播放...\n\n")
        self.theory_text.setStyleSheet("""
            background-color: #2d2d2d;
            color: #ffffff;
            border: 2px solid #61c0bf;
            border-radius: 8px;
            font-family: "Segoe UI", Arial, sans-serif;
            font-size: 11pt;  # 增大字体大小
            line-height: 1.6;
            min-height: 220px;  # 设置最小高度，增大显示区域
        """)
        layout.addWidget(self.theory_text)
        
        parent_layout.addWidget(group_box)
    
    def create_note_history_area(self, parent_layout):
        """创建音符历史区域 - 缩小尺寸"""
        group_box = QGroupBox("音符历史")
        layout = QVBoxLayout(group_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        self.note_history_list = QListWidget()
        self.note_history_list.setMaximumHeight(100)  # 限制最大高度，缩小显示区域
        self.note_history_list.setStyleSheet("""
            background-color: #2d2d2d;
            color: #ffffff;
            border: 2px solid #61c0bf;
            border-radius: 8px;
            font-size: 9pt;  # 减小字体大小
        """)
        layout.addWidget(self.note_history_list)
        
        parent_layout.addWidget(group_box)
    
    def create_system_log_area(self, parent_layout):
        """创建系统日志区域"""
        group_box = QGroupBox("系统日志")
        layout = QVBoxLayout(group_box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)
        
        # 日志过滤和错误忽略
        filter_layout = QHBoxLayout()
        filter_layout.setSpacing(15)
        
        self.debug_check = QCheckBox("调试")
        self.debug_check.setChecked(True)
        self.info_check = QCheckBox("信息")
        self.info_check.setChecked(True)
        self.warning_check = QCheckBox("警告")
        self.warning_check.setChecked(True)
        self.error_check = QCheckBox("错误")
        self.error_check.setChecked(True)
        
        # 添加错误忽略复选框
        self.ignore_non_fatal_check = QCheckBox("忽略非致命错误")
        self.ignore_non_fatal_check.setChecked(False)
        self.ignore_non_fatal_check.setToolTip("忽略不影响MIDI播放的错误")
        
        filter_layout.addWidget(self.debug_check)
        filter_layout.addWidget(self.info_check)
        filter_layout.addWidget(self.warning_check)
        filter_layout.addWidget(self.error_check)
        filter_layout.addWidget(self.ignore_non_fatal_check)
        
        layout.addLayout(filter_layout)
        
        # 日志显示（固定高度120px）- 深色背景
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        self.log_text.setStyleSheet("""
            background-color: #1a1a1a;
            color: #ffffff;
            border: 2px solid #61c0bf;
            border-radius: 8px;
            font-family: "Consolas", monospace;
            font-size: 9pt;
            padding: 8px;
        """)
        layout.addWidget(self.log_text)
        
        parent_layout.addWidget(group_box)
    
    def connect_signals(self):
        """连接信号槽"""
        self.update_status.connect(self.on_status_updated)
        self.update_progress.connect(self.on_progress_updated)
        self.update_active_notes.connect(self.on_active_notes_updated)
        self.update_performance.connect(self.on_performance_updated)
        self.update_note_history.connect(self.on_note_history_updated)
        self.update_log.connect(self.on_log_updated)
        self.update_port_status.connect(self.on_port_status_updated)
        self.update_file_list.connect(self.on_file_list_updated)
        self.update_fps.connect(self.on_fps_updated)
        self.update_music_theory.connect(self.on_music_theory_updated)
    
    def init_midi_system(self):
        """初始化MIDI系统"""
        try:
            # 获取输出端口列表
            output_ports = mido.get_output_names()
            self.port1_combo.addItems(output_ports)
            self.port2_combo.addItems(output_ports)
            
            self.log("MIDI系统初始化成功", "info")
            self.global_status.setText("就绪")
            self.global_status.setStyleSheet("color: #61c0bf; font-weight: bold;")
        except Exception as e:
            self.log(f"MIDI系统初始化失败: {str(e)}", "error")
            self.global_status.setText("MIDI系统错误")
            self.global_status.setStyleSheet("color: #dc3545; font-weight: bold;")
    
    def init_threads(self):
        """初始化线程和队列"""
        # 事件队列
        self.midi_event_queue = queue.Queue(maxsize=100000)  # 增大队列容量
        self.parse_queue = queue.Queue(maxsize=100)
        
        # 根据模式选择线程数量
        if self.black_midi_mode:
            import multiprocessing
            self.num_midi_threads = multiprocessing.cpu_count() * 2
        else:
            self.num_midi_threads = 2
        
        # 创建多个MIDI工作线程
        self.midi_threads = []
        for i in range(self.num_midi_threads):
            thread = threading.Thread(target=self.midi_worker, args=(i,), daemon=True)
            self.midi_threads.append(thread)
            thread.start()
        
        # 其他线程
        self.parse_thread = threading.Thread(target=self.parse_worker, daemon=True)
        self.note_thread = threading.Thread(target=self.note_worker, daemon=True)
        
        self.parse_thread.start()
        self.note_thread.start()
    
    def start_monitors(self):
        """启动监控定时器"""
        # FPS监控定时器
        self.fps_timer = QTimer()
        self.fps_timer.timeout.connect(self.update_fps_counter)
        self.fps_timer.start(1000)  # 每秒更新一次
        
        # 性能监控定时器（10ms更新一次）
        self.performance_timer = QTimer()
        self.performance_timer.timeout.connect(self.update_performance_data)
        self.performance_timer.start(10)  # 10ms更新一次
        
        # 实时性能显示定时器
        self.realtime_timer = QTimer()
        self.realtime_timer.timeout.connect(self.update_realtime_display)
        self.realtime_timer.start(100)  # 100ms更新一次
    
    def toggle_black_midi_mode(self, state):
        """切换黑乐谱模式"""
        self.black_midi_mode = (state == Qt.CheckState.Checked)
        if self.black_midi_mode:
            self.log("启用黑乐谱模式，优化性能", "info")
            # 重启线程以应用新配置
            self.restart_threads()
        else:
            self.log("禁用黑乐谱模式，恢复标准模式", "info")
            self.restart_threads()
    
    def toggle_show_active_notes(self, state):
        """切换显示活跃音符"""
        self.show_active_notes = (state == Qt.CheckState.Checked)
        if not self.show_active_notes:
            self.active_notes_table.setRowCount(0)
            if hasattr(self, 'float_window') and self.float_window.isVisible():
                self.float_window.update_notes([])
    
    def restart_threads(self):
        """重启工作线程"""
        # 停止当前线程
        self.stop_event.set()
        time.sleep(0.1)
        
        # 重置事件
        self.stop_event.clear()
        
        # 根据模式重新配置线程
        if self.black_midi_mode:
            import multiprocessing
            self.num_midi_threads = multiprocessing.cpu_count() * 2
            self.batch_size = 100
        else:
            self.num_midi_threads = 2
            self.batch_size = 10
        
        # 重启线程
        self.init_threads()
    
    def toggle_port_connection(self, port_num):
        """切换端口连接状态"""
        if port_num == 1:
            if not self.port1_connected:
                self.connect_port(1)
            else:
                self.disconnect_port(1)
        else:
            if not self.port2_connected:
                self.connect_port(2)
            else:
                self.disconnect_port(2)
    
    def connect_port(self, port_num):
        """连接MIDI端口"""
        try:
            if port_num == 1:
                port_name = self.port1_combo.currentText()
                if port_name:
                    # 使用低延迟模式
                    self.port1_out = mido.open_output(port_name, latency=0.001)
                    self.port1_connected = True
                    self.port1_name = port_name
                    self.update_port_status.emit(1, True)
                    self.log(f"端口1连接成功: {port_name}", "info")
                    self.global_status.setText(f"端口1已连接: {port_name}")
                    self.global_status.setStyleSheet("color: #28a745; font-weight: bold;")
            else:
                port_name = self.port2_combo.currentText()
                if port_name:
                    self.port2_out = mido.open_output(port_name, latency=0.001)
                    self.port2_connected = True
                    self.port2_name = port_name
                    self.update_port_status.emit(2, True)
                    self.log(f"端口2连接成功: {port_name}", "info")
                    self.global_status.setText(f"端口2已连接: {port_name}")
                    self.global_status.setStyleSheet("color: #28a745; font-weight: bold;")
        except Exception as e:
            self.log(f"端口{port_num}连接失败: {str(e)}", "error")
            self.global_status.setText(f"端口{port_num}连接失败")
            self.global_status.setStyleSheet("color: #dc3545; font-weight: bold;")
    
    def disconnect_port(self, port_num):
        """断开MIDI端口连接"""
        try:
            if port_num == 1 and self.port1_connected:
                self.port1_out.close()
                self.port1_connected = False
                self.update_port_status.emit(1, False)
                self.log(f"端口1断开连接: {self.port1_name}", "info")
            elif port_num == 2 and self.port2_connected:
                self.port2_out.close()
                self.port2_connected = False
                self.update_port_status.emit(2, False)
                self.log(f"端口2断开连接: {self.port2_name}", "info")
            
            # 更新全局状态
            active_ports = sum([self.port1_connected, self.port2_connected])
            if active_ports == 0:
                self.global_status.setText("就绪")
                self.global_status.setStyleSheet("color: #61c0bf; font-weight: bold;")
            elif self.port1_connected:
                self.global_status.setText(f"端口1已连接: {self.port1_name}")
                self.global_status.setStyleSheet("color: #28a745; font-weight: bold;")
            else:
                self.global_status.setText(f"端口2已连接: {self.port2_name}")
                self.global_status.setStyleSheet("color: #28a745; font-weight: bold;")
                
        except Exception as e:
            self.log(f"端口{port_num}断开失败: {str(e)}", "error")
    
    def test_connections(self):
        """测试端口连接"""
        try:
            # 播放测试和弦 (C major)
            test_notes = [60, 64, 67]  # C4, E4, G4
            
            for note in test_notes:
                if self.port1_connected:
                    self.port1_out.send(Message('note_on', note=note, velocity=64))
                if self.port2_connected:
                    self.port2_out.send(Message('note_on', note=note, velocity=64))
            
            time.sleep(0.5)
            
            for note in test_notes:
                if self.port1_connected:
                    self.port1_out.send(Message('note_off', note=note, velocity=64))
                if self.port2_connected:
                    self.port2_out.send(Message('note_off', note=note, velocity=64))
            
            self.log("连接测试完成", "info")
            self.global_status.setText("连接测试完成")
            self.global_status.setStyleSheet("color: #61c0bf; font-weight: bold;")
        except Exception as e:
            self.log(f"连接测试失败: {str(e)}", "error")
            self.global_status.setText("连接测试失败")
            self.global_status.setStyleSheet("color: #dc3545; font-weight: bold;")
    
    def add_files(self):
        """添加MIDI文件"""
        files, _ = QFileDialog.getOpenFileNames(self, "选择MIDI文件", "", "MIDI Files (*.mid *.midi)")
        if files:
            added_count = 0
            for file in files:
                if file not in self.playlist:
                    self.playlist.append(file)
                    added_count += 1
            self.update_file_list.emit(self.playlist)
            self.log(f"添加了 {added_count} 个文件", "info")
            self.global_status.setText(f"已添加 {added_count} 个文件")
            self.global_status.setStyleSheet("color: #61c0bf; font-weight: bold;")
    
    def remove_file(self):
        """移除选中文件"""
        selected_items = self.file_list.selectedItems()
        if selected_items:
            removed_count = 0
            for item in selected_items:
                file_name = item.text()
                # 在播放列表中查找完整路径
                for file_path in self.playlist:
                    if os.path.basename(file_path) == file_name:
                        index = self.playlist.index(file_path)
                        self.playlist.pop(index)
                        if self.current_file_index == index:
                            self.stop_playback()
                            self.current_file_index = -1
                        removed_count += 1
                        break
            self.update_file_list.emit(self.playlist)
            self.log(f"移除了 {removed_count} 个文件", "info")
            self.global_status.setText(f"已移除 {removed_count} 个文件")
            self.global_status.setStyleSheet("color: #61c0bf; font-weight: bold;")
    
    def clear_files(self):
        """清空文件列表"""
        self.stop_playback()
        file_count = len(self.playlist)
        self.playlist.clear()
        self.current_file_index = -1
        self.update_file_list.emit(self.playlist)
        self.log("文件列表已清空", "info")
        self.global_status.setText(f"文件列表已清空 ({file_count} 个文件)")
        self.global_status.setStyleSheet("color: #61c0bf; font-weight: bold;")
    
    def on_file_double_clicked(self, item):
        """文件双击播放"""
        file_name = item.text()
        # 在播放列表中查找完整路径
        for i, file_path in enumerate(self.playlist):
            if os.path.basename(file_path) == file_name:
                self.current_file_index = i
                self.play_current_file()
                break
    
    def toggle_play_pause(self):
        """切换播放/暂停"""
        if not self.playlist:
            QMessageBox.warning(self, "警告", "请先添加MIDI文件")
            return
        
        if not self.is_playing:
            if self.current_file_index == -1:
                self.current_file_index = 0
            self.play_current_file()
        else:
            self.pause_playback()
    
    def play_current_file(self):
        """播放当前文件"""
        if self.current_file_index >= 0 and self.current_file_index < len(self.playlist):
            file_path = self.playlist[self.current_file_index]
            self.load_and_play_midi(file_path)
    
    def load_and_play_midi(self, file_path):
        """加载并播放MIDI文件"""
        try:
            # 停止当前播放
            self.stop_playback()
            
            # 清空队列
            self.clear_queues()
            
            # 解析MIDI文件
            midi_file = MidiFile(file_path)
            self.total_time = midi_file.length
            
            # 重置所有相关状态
            self.message_count = 0
            self.current_time = 0
            self.playback_complete = False
            self.start_time = time.time()
            self.is_playing = True
            self.is_paused = False
            
            # 提取MIDI文件中的音乐信息
            self.extract_midi_info(midi_file)
            
            # 更新音乐信息显示
            self.update_music_info_display()
            
            # 将解析任务放入队列
            self.parse_queue.put((midi_file, file_path))
            
            # 更新UI
            self.update_playback_ui(f"播放中: {os.path.basename(file_path)}", "#28a745")
            
            self.log(f"开始播放: {file_path}", "info")
            self.global_status.setText(f"播放中: {os.path.basename(file_path)}")
            self.global_status.setStyleSheet("color: #28a745; font-weight: bold;")
            
        except Exception as e:
            self.log(f"播放失败: {str(e)}", "error")
            self.global_status.setText("播放失败")
            self.global_status.setStyleSheet("color: #dc3545; font-weight: bold;")
            self.stop_playback()
    
    def extract_midi_info(self, midi_file):
        """提取MIDI文件中的音乐信息"""
        self.current_tempo = 120
        self.current_time_signature = (4, 4)
        self.current_key = None
        
        for track in midi_file.tracks:
            for msg in track:
                if msg.type == 'set_tempo':
                    self.current_tempo = round(mido.tempo2bpm(msg.tempo))
                elif msg.type == 'time_signature':
                    self.current_time_signature = (msg.numerator, msg.denominator)
                elif msg.type == 'key_signature':
                    self.current_key = msg.key
    
    def update_music_info_display(self):
        """更新音乐信息显示"""
        self.bpm_label.setText(f"速度: {self.current_tempo} BPM ({self.get_tempo_name()})")
        self.time_sig_label.setText(f"拍号: {self.current_time_signature[0]}/{self.current_time_signature[1]}")
        self.key_label.setText(f"调号: {self.get_key_name() if self.current_key is not None else '未知'}")
    
    def get_tempo_name(self):
        """根据BPM返回速度名称"""
        if self.current_tempo < 60:
            return "慢板"
        elif self.current_tempo < 76:
            return "行板"
        elif self.current_tempo < 108:
            return "中速"
        elif self.current_tempo < 120:
            return "快板"
        elif self.current_tempo < 168:
            return "急板"
        else:
            return "极快"
    
    def get_key_name(self):
        """将调号转换为中文名称"""
        key_names = {
            'C': 'C大调', 'a': 'a小调',
            'G': 'G大调', 'e': 'e小调',
            'D': 'D大调', 'b': 'b小调',
            'A': 'A大调', 'f#': '升f小调',
            'E': 'E大调', 'c#': '升c小调',
            'B': 'B大调', 'g#': '升g小调',
            'F#': '升F大调', 'd#': '升d小调',
            'Gb': '降G大调', 'bb': '降b小调',
            'Db': '降D大调', 'ab': '降a小调',
            'Ab': '降A大调', 'f': 'f小调',
            'Eb': '降E大调', 'c': 'c小调',
            'Bb': '降B大调', 'g': 'g小调',
            'F': 'F大调', 'd': 'd小调'
        }
        return key_names.get(self.current_key, self.current_key) if self.current_key else "未知"
    
    def pause_playback(self):
        """暂停播放"""
        if self.is_playing and not self.is_paused:
            self.is_paused = True
            self.pause_event.clear()
            self.update_playback_ui("已暂停", "#ffc107")
            self.log("播放已暂停", "info")
            self.global_status.setText("播放已暂停")
            self.global_status.setStyleSheet("color: #ffc107; font-weight: bold;")
        elif self.is_playing and self.is_paused:
            self.is_paused = False
            self.pause_event.set()
            current_file = os.path.basename(self.playlist[self.current_file_index]) if self.playlist and self.current_file_index != -1 else ""
            self.update_playback_ui(f"播放中: {current_file}", "#28a745")
            self.log("播放已恢复", "info")
            self.global_status.setText(f"播放中: {current_file}")
            self.global_status.setStyleSheet("color: #28a745; font-weight: bold;")
    
    def stop_playback(self):
        """停止播放"""
        self.is_playing = False
        self.is_paused = False
        self.playback_complete = False
        self.pause_event.set()
        self.start_time = None
        
        # 发送所有音符关闭消息
        self.all_notes_off()
        
        # 清空队列
        self.clear_queues()
        
        # 更新UI
        self.update_playback_ui("已停止", "#dc3545")
        
        # 清空活跃音符
        self.active_notes.clear()
        self.update_active_notes.emit([])
        
        # 更新乐理信息
        self.update_music_theory.emit("等待音符播放...\n\n功能说明：将显示当前音符的乐理信息、和弦分析及音程关系")
        
        self.log("播放已停止", "info")
        self.global_status.setText("就绪")
        self.global_status.setStyleSheet("color: #61c0bf; font-weight: bold;")
    
    def clear_queues(self):
        """清空所有队列"""
        try:
            while True:
                try:
                    self.midi_event_queue.get_nowait()
                except queue.Empty:
                    break
            while True:
                try:
                    self.parse_queue.get_nowait()
                except queue.Empty:
                    break
        except Exception as e:
            self.log(f"清空队列错误: {str(e)}", "error", is_fatal=False)
    
    def update_playback_ui(self, status_text, color):
        """更新播放UI状态"""
        self.update_status.emit(status_text, color)
        if "播放中" in status_text:
            self.play_btn.setText("暂停")
        elif "已暂停" in status_text:
            self.play_btn.setText("播放")
        else:
            self.play_btn.setText("播放")
            self.progress_bar.setValue(0)
            self.time_label.setText("00:00 / 00:00")
    
    def play_previous(self):
        """播放上一首"""
        if self.playlist:
            if self.current_file_index <= 0:
                self.current_file_index = len(self.playlist) - 1
            else:
                self.current_file_index -= 1
            self.play_current_file()
    
    def play_next(self):
        """播放下一首"""
        if self.playlist:
            if self.current_file_index >= len(self.playlist) - 1:
                self.current_file_index = 0
            else:
                self.current_file_index += 1
            self.play_current_file()
    
    def all_notes_off(self):
        """关闭所有音符"""
        try:
            for channel in range(16):
                cc_message = Message('control_change', channel=channel, control=123, value=0)
                if self.port1_connected:
                    self.port1_out.send(cc_message)
                if self.port2_connected:
                    self.port2_out.send(cc_message)
            
            for note in list(self.active_notes.keys()):
                note_off = Message('note_off', note=note, velocity=0)
                if self.port1_connected:
                    self.port1_out.send(note_off)
                if self.port2_connected:
                    self.port2_out.send(note_off)
            
            self.active_notes.clear()
            self.update_active_notes.emit([])
        except Exception as e:
            self.log(f"关闭所有音符失败: {str(e)}", "error")
    
    def parse_worker(self):
        """文件解析工作线程"""
        while not self.stop_event.is_set():
            try:
                midi_file, file_path = self.parse_queue.get(timeout=0.1)
                
                start_time = time.time()
                events = []
                current_time = 0
                
                for msg in midi_file:
                    current_time += msg.time
                    
                    if msg.type in ['note_on', 'note_off', 'control_change', 
                                   'program_change', 'pitchwheel', 'set_tempo',
                                   'time_signature', 'key_signature']:
                        # 黑乐谱优化：过滤力度为0的note_on事件
                        if (self.black_midi_mode and self.filter_zero_velocity_check.isChecked() and
                            msg.type == 'note_on' and msg.velocity == 0):
                            continue
                            
                        events.append((current_time, msg))
                
                self.log(f"解析完成: {file_path}, 事件数: {len(events)}", "debug")
                
                # 将事件放入MIDI事件队列
                for event_time, msg in events:
                    self.midi_event_queue.put((event_time, msg))
                
                self.parse_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                self.log(f"解析线程错误: {str(e)}", "error", is_fatal=False)
                continue
    
    def midi_worker(self, thread_id):
        """MIDI发送工作线程"""
        local_event_count = 0
        
        while not self.stop_event.is_set():
            try:
                if not self.is_playing or self.playback_complete:
                    time.sleep(0.001 if self.black_midi_mode else 0.01)
                    continue
                
                # 检查暂停状态
                self.pause_event.wait()
                
                # 确保开始时间有效
                if self.start_time is None:
                    self.start_time = time.time()
                
                # 获取当前播放时间
                elapsed_time = time.time() - self.start_time
                
                # 处理队列中的事件
                event_processed = False
                batch_size = 100 if self.black_midi_mode else 10
                batch_count = 0
                
                while (not self.midi_event_queue.empty() and self.is_playing and 
                       not self.playback_complete and batch_count < batch_size):
                    
                    event_time, msg = self.midi_event_queue.queue[0]
                    
                    if event_time <= elapsed_time:
                        # 弹出事件
                        self.midi_event_queue.get()
                        event_processed = True
                        batch_count += 1
                        
                        # 记录开始时间用于延迟计算
                        start_send = time.time()
                        
                        # 处理元消息（只在主线程处理）
                        if msg.is_meta:
                            if thread_id == 0:
                                self.handle_meta_message(msg)
                            continue
                        
                        # 发送MIDI消息到连接的端口
                        self.send_midi_message(msg)
                        
                        # 计算延迟
                        latency = (time.time() - start_send) * 1000
                        self.queue_lengths.append(latency)
                        if len(self.queue_lengths) > 100:
                            self.queue_lengths.pop(0)
                        
                        # 更新消息计数
                        local_event_count += 1
                        if local_event_count >= 100:
                            with self.counter_lock:
                                self.message_count += local_event_count
                                self.session_message_count += local_event_count
                            local_event_count = 0
                        
                        # 处理音符事件
                        self.handle_note_event(msg)
                        
                    else:
                        break
                
                # 更新当前播放时间
                self.current_time = elapsed_time
                
                # 检查播放是否完成
                self.check_playback_complete(elapsed_time, event_processed)
                
                # 更新进度（黑乐谱模式下降低更新频率）
                if (self.total_time > 0 and (not self.black_midi_mode or 
                    (self.black_midi_mode and batch_count % 10 == 0))):
                    progress = int((self.current_time / self.total_time) * 1000)
                    time_text = f"{self.format_time(self.current_time)} / {self.format_time(self.total_time)}"
                    self.update_progress.emit(progress, 1000, time_text)
                
                # 根据是否处理了事件调整睡眠时间
                if event_processed:
                    time.sleep(0.0001 if self.black_midi_mode else 0.001)
                else:
                    time.sleep(0.001 if self.black_midi_mode else 0.01)
                    
            except Exception as e:
                # 记录非致命错误，不影响线程继续运行
                self.log(f"MIDI线程{thread_id}错误: {str(e)}", "error", is_fatal=False)
                time.sleep(0.1)
                continue
    
    def handle_meta_message(self, msg):
        """处理元消息"""
        try:
            if msg.type == 'set_tempo':
                self.current_tempo = round(mido.tempo2bpm(msg.tempo))
                self.bpm_label.setText(f"速度: {self.current_tempo} BPM ({self.get_tempo_name()})")
            elif msg.type == 'time_signature':
                self.current_time_signature = (msg.numerator, msg.denominator)
                self.time_sig_label.setText(f"拍号: {self.current_time_signature[0]}/{self.current_time_signature[1]}")
            elif msg.type == 'key_signature':
                self.current_key = msg.key
                self.key_label.setText(f"调号: {self.get_key_name() if self.current_key is not None else '未知'}")
        except Exception as e:
            self.log(f"处理元消息错误: {str(e)}", "error", is_fatal=False)
    
    def send_midi_message(self, msg):
        """发送MIDI消息"""
        try:
            if self.port1_connected:
                self.port1_out.send(msg)
            if self.port2_connected:
                self.port2_out.send(msg)
        except Exception as send_e:
            self.log(f"MIDI发送错误: {str(send_e)}", "error", is_fatal=False)
    
    def check_playback_complete(self, elapsed_time, event_processed):
        """检查播放是否完成"""
        try:
            if self.total_time > 0 and elapsed_time >= self.total_time and self.midi_event_queue.empty() and not event_processed:
                if not self.playback_complete:
                    self.log("播放完成", "info")
                    self.playback_complete = True
                    # 延迟停止，确保所有事件都被处理
                    QTimer.singleShot(500, self.stop_playback)
        except Exception as e:
            self.log(f"检查播放完成错误: {str(e)}", "error", is_fatal=False)
    
    def note_worker(self):
        """音符处理工作线程"""
        while not self.stop_event.is_set():
            try:
                if not self.is_playing or not self.active_notes or self.playback_complete or not self.show_active_notes:
                    time.sleep(0.01)
                    continue
                
                # 更新活跃音符的时长
                current_time = time.time()
                updated_notes = []
                
                # 黑乐谱优化：限制活跃音符显示数量
                display_limit = min(50, len(self.active_notes)) if self.black_midi_mode else len(self.active_notes)
                count = 0
                
                for note, info in list(self.active_notes.items()):
                    if count >= display_limit:
                        break
                    duration = current_time - info['start_time']
                    updated_info = info.copy()
                    updated_info['duration'] = duration
                    updated_notes.append({
                        'note': note,
                        'name': info['name'],
                        'octave': info['octave'],
                        'frequency': info['frequency'],
                        'velocity': info['velocity'],
                        'duration': round(duration, 2)
                    })
                    count += 1
                
                # 发送活跃音符更新
                if updated_notes:
                    self.update_active_notes.emit(updated_notes)
                    
                    # 黑乐谱优化：降低乐理分析频率
                    if not self.black_midi_mode or (len(updated_notes) <= 5 and count % 5 == 0):
                        try:
                            self.analyze_current_notes(updated_notes)
                        except Exception as analysis_e:
                            self.log(f"音符分析错误: {str(analysis_e)}", "error", is_fatal=False)
                
                # 黑乐谱模式下增加睡眠时间
                time.sleep(0.05 if self.black_midi_mode else 0.01)
                
            except Exception as e:
                self.log(f"音符线程错误: {str(e)}", "error", is_fatal=False)
                time.sleep(0.1)
                continue
    
    def handle_note_event(self, msg):
        """处理音符事件"""
        try:
            if msg.type == 'note_on' and msg.velocity > 0:
                self.handle_note_on(msg.note, msg.velocity)
            elif msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
                self.handle_note_off(msg.note)
        except Exception as note_e:
            self.log(f"音符处理错误: {str(note_e)}", "error", is_fatal=False)
    
    def handle_note_on(self, note, velocity):
        """处理音符开启事件"""
        try:
            note_info = self.get_note_info(note)
            note_info['velocity'] = velocity
            note_info['start_time'] = time.time()
            
            # 黑乐谱优化：限制活跃音符数量
            if self.black_midi_mode and len(self.active_notes) >= self.max_active_notes:
                # 移除最旧的音符
                if self.active_notes:
                    oldest_note = min(self.active_notes.keys(), key=lambda x: self.active_notes[x]['start_time'])
                    del self.active_notes[oldest_note]
            
            self.active_notes[note] = note_info
            
            # 添加到历史记录（黑乐谱模式下降低频率）
            if not self.black_midi_mode or (len(self.note_history) % 10 == 0):
                self.note_history.appendleft({
                    'time': datetime.now().strftime('%H:%M:%S'),
                    'note': note,
                    'name': note_info['name'],
                    'octave': note_info['octave'],
                    'velocity': velocity,
                    'type': 'ON'
                })
                self.update_note_history.emit(list(self.note_history))
                
        except Exception as e:
            self.log(f"处理音符开启错误: {str(e)}", "error", is_fatal=False)
    
    def handle_note_off(self, note):
        """处理音符关闭事件"""
        try:
            if note in self.active_notes:
                # 计算持续时间
                duration = time.time() - self.active_notes[note]['start_time']
                
                # 添加到历史记录（黑乐谱模式下降低频率）
                if not self.black_midi_mode or (len(self.note_history) % 10 == 0):
                    self.note_history.appendleft({
                        'time': datetime.now().strftime('%H:%M:%S'),
                        'note': note,
                        'name': self.active_notes[note]['name'],
                        'octave': self.active_notes[note]['octave'],
                        'duration': round(duration, 2),
                        'type': 'OFF'
                    })
                    self.update_note_history.emit(list(self.note_history))
                
                # 从活跃音符中移除
                del self.active_notes[note]
                
        except Exception as e:
            self.log(f"处理音符关闭错误: {str(e)}", "error", is_fatal=False)
    
    def get_note_info(self, note):
        """获取音符信息"""
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        note_index = note % 12
        octave = (note // 12) - 1
        name = note_names[note_index]
        
        # 计算频率
        frequency = 440.0 * (2.0 ** ((note - 69) / 12.0))
        
        return {
            'name': name,
            'octave': octave,
            'frequency': round(frequency, 2)
        }
    
    def analyze_current_notes(self, notes):
        """分析当前音符并生成乐理知识信息"""
        if not notes or not self.show_active_notes:
            return
            
        # 提取音符名称和八度
        note_names = [f"{note['name']}{note['octave']}" for note in notes]
        note_numbers = [note['note'] for note in notes]
        
        # 单音符分析
        if len(notes) == 1:
            note = notes[0]
            theory_text = self.analyze_single_note(note)
        # 和弦分析
        else:
            theory_text = self.analyze_chord(notes)
        
        # 添加通用音乐信息
        theory_text += "\n\n"
        theory_text += f"拍号: {self.current_time_signature[0]}/{self.current_time_signature[1]}\n"
        theory_text += f"速度: {self.current_tempo} BPM ({self.get_tempo_name()})\n"
        if self.current_key:
            theory_text += f"当前调号: {self.get_key_name()}\n"
        
        self.update_music_theory.emit(theory_text)
    
    def analyze_single_note(self, note):
        """分析单个音符的乐理信息"""
        note_name = note['name']
        octave = note['octave']
        frequency = note['frequency']
        note_number = note['note']
        
        # 音程关系（相对于C音）
        c_note = 60 + (octave - 4) * 12  # C4为60
        if note_number < c_note:
            c_octave = octave - 1
            interval = note_number - (c_note - 12)
        else:
            c_octave = octave
            interval = note_number - c_note
            
        interval_name = self.get_interval_name(interval)
        
        # 大调音阶中的位置
        major_positions = {}
        major_scales = self.get_major_scales()
        for key, scale in major_scales.items():
            # 调整到当前八度
            base_note = self.get_key_root_note(key)
            base_note_in_octave = base_note % 12
            note_in_octave = note_number % 12
            
            if note_in_octave in scale:
                position = scale.index(note_in_octave) + 1
                major_positions[key] = position
        
        # 构建文本
        text = f"▶ 音符: {note_name}{octave}\n"
        text += f"   频率: {frequency} Hz\n"
        text += f"   力度: {note['velocity']} (0-127)\n"
        text += f"   与C{c_octave}音程: {interval_name}\n\n"
        
        text += "在大调中的位置:\n"
        # 只显示几个常见大调
        common_keys = ['C', 'G', 'D', 'F', 'Bb', 'A', 'Eb']
        for key in common_keys:
            if key in major_positions:
                degree_name = self.get_degree_name(major_positions[key])
                text += f"   {key}大调: 第{major_positions[key]}级 ({degree_name})\n"
        
        # 当前调式信息
        key_name = ""
        if self.current_key and self.current_key[0].upper() in major_positions:
            key_name = self.get_key_name()
            position = major_positions[self.current_key[0].upper()]
            degree_name = self.get_degree_name(position)
            text += f"\n当前调式 ({key_name}) 中: 第{position}级 ({degree_name})\n"
        
        # 音阶信息
        if self.current_key and key_name:
            scale_notes = self.get_scale_notes(self.current_key)
            text += f"\n{key_name}音阶: {', '.join(scale_notes)}\n"
        
        return text
    
    def analyze_chord(self, notes):
        """分析和弦的乐理信息"""
        # 提取音符（忽略八度差异）
        note_classes = sorted(list(set([note['note'] % 12 for note in notes])))
        note_names = [f"{note['name']}{note['octave']}" for note in notes]
        
        # 识别和弦
        chord_name, chord_type, chord_notes = self.identify_chord(note_classes)
        
        # 构建文本
        text = f"▶ 和弦: {chord_name} ({chord_type})\n"
        text += f"   构成音: {', '.join(chord_notes)}\n"
        text += f"   音符: {', '.join(note_names[:5])}{'...' if len(note_names) > 5 else ''}\n\n"
        
        # 和弦属性（基于当前调式推断）
        chord_degree = ""
        if self.current_key:
            key_name = self.get_key_name()
            chord_degree = self.get_chord_degree(chord_name, self.current_key)
            if chord_degree:
                text += f"在{key_name}中: {chord_degree}\n\n"
        
        return text
    
    def get_interval_name(self, interval):
        """获取音程名称"""
        interval = interval % 12
        interval_names = [
            "纯一度", "小二度", "大二度", "小三度", "大三度",
            "纯四度", "增四度/减五度", "纯五度", "小六度",
            "大六度", "小七度", "大七度"
        ]
        return interval_names[interval]
    
    def get_degree_name(self, degree):
        """获取音阶度数名称"""
        degree_names = [
            "主音", "上主音", "中音", "下属音", 
            "属音", "下中音", "导音"
        ]
        return degree_names[degree - 1] if 1 <= degree <= 7 else f"第{degree}级"
    
    def get_major_scales(self):
        """获取各大调的音阶"""
        return {
            'C': [0, 2, 4, 5, 7, 9, 11],
            'G': [0, 2, 4, 5, 7, 9, 10],
            'D': [0, 2, 4, 6, 7, 9, 10],
            'A': [0, 2, 4, 6, 7, 9, 11],
            'E': [0, 1, 4, 6, 7, 9, 11],
            'B': [0, 1, 4, 6, 7, 8, 11],
            'F#': [0, 1, 3, 6, 7, 8, 11],
            'Gb': [0, 1, 3, 6, 7, 8, 11],
            'Db': [0, 1, 3, 5, 7, 8, 11],
            'Ab': [0, 1, 3, 5, 7, 8, 10],
            'Eb': [0, 2, 3, 5, 7, 9, 10],
            'Bb': [0, 2, 3, 5, 7, 9, 11],
            'F': [0, 2, 4, 5, 7, 8, 11]
        }
    
    def get_key_root_note(self, key):
        """获取调号的根音MIDI编号"""
        key_offsets = {
            'C': 0, 'G': 7, 'D': 2, 'A': 9, 'E': 4, 'B': 11,
            'F#': 6, 'Gb': 6, 'Db': 1, 'Ab': 8, 'Eb': 3, 'Bb': 10, 'F': 5
        }
        if not key:
            return 60  # 默认C4
        root = key[0].upper()
        return 60 + key_offsets.get(root, 0)
    
    def get_scale_notes(self, key):
        """获取调式的音阶音符名称"""
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        if not key:
            return []
            
        root_note = self.get_key_root_note(key) % 12
        is_major = key.isupper() if len(key) == 1 else key[0].isupper()
        
        if is_major:
            # 大调
            intervals = [0, 2, 4, 5, 7, 9, 11]
        else:
            # 小调（自然小调）
            intervals = [0, 2, 3, 5, 7, 8, 10]
            
        scale_notes = [(root_note + i) % 12 for i in intervals]
        return [note_names[i] for i in scale_notes]
    
    def identify_chord(self, note_classes):
        """识别和弦类型"""
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        
        # 简化为相对根音的半音数
        root = note_classes[0]
        relative_notes = [(n - root) % 12 for n in note_classes]
        relative_notes_sorted = sorted(relative_notes)
        
        # 常见和弦类型的音程模式
        chord_patterns = {
            '大三和弦': ([0, 4, 7], 'Maj', '大三和弦'),
            '小三和弦': ([0, 3, 7], 'm', '小三和弦'),
            '增三和弦': ([0, 4, 8], 'aug', '增三和弦'),
            '减三和弦': ([0, 3, 6], 'dim', '减三和弦'),
            '七和弦': ([0, 4, 7, 10], '7', '属七和弦'),
            '大七和弦': ([0, 4, 7, 11], 'Maj7', '大七和弦'),
            '小七和弦': ([0, 3, 7, 10], 'm7', '小七和弦'),
            '减七和弦': ([0, 3, 6, 9], 'dim7', '减七和弦'),
            '半减七和弦': ([0, 3, 6, 10], 'm7b5', '半减七和弦'),
            '六和弦': ([0, 4, 7, 9], '6', '六和弦'),
            '九和弦': ([0, 4, 7, 10, 2], '9', '九和弦')
        }
        
        # 匹配和弦模式
        for name, (pattern, symbol, desc) in chord_patterns.items():
            if self.match_chord_pattern(relative_notes_sorted, pattern):
                root_name = note_names[root]
                chord_notes = [note_names[(root + i) % 12] for i in pattern]
                return f"{root_name}{symbol}", desc, chord_notes
        
        # 如果没有匹配到已知和弦，返回基本信息
        root_name = note_names[root]
        chord_notes = [note_names[n] for n in note_classes]
        return f"{root_name}和弦", f"由{len(note_classes)}个音符组成", chord_notes
    
    def match_chord_pattern(self, notes, pattern):
        """匹配和弦音程模式"""
        # 如果音符数量少于和弦模式，不匹配
        if len(notes) < len(pattern):
            return False
            
        # 检查模式中的所有音程是否都在音符中
        for p in pattern:
            if p not in notes:
                return False
        return True
    
    def get_chord_degree(self, chord_name, key):
        """获取和弦在当前调式中的级数"""
        if not key:
            return None
            
        # 提取和弦根音
        root = chord_name[0]
        if len(chord_name) > 1 and chord_name[1] in ['#', 'b']:
            root += chord_name[1]
        
        # 大调中的和弦级数
        major_chords = {
            'C': ['C', 'Dm', 'Em', 'F', 'G', 'Am', 'Bdim'],
            'G': ['G', 'Am', 'Bm', 'C', 'D', 'Em', 'F#dim'],
            'D': ['D', 'Em', 'F#m', 'G', 'A', 'Bm', 'C#dim'],
            'A': ['A', 'Bm', 'C#m', 'D', 'E', 'F#m', 'G#dim'],
            'E': ['E', 'F#m', 'G#m', 'A', 'B', 'C#m', 'D#dim'],
            'B': ['B', 'C#m', 'D#m', 'E', 'F#', 'G#m', 'A#dim'],
            'F#': ['F#', 'G#m', 'A#m', 'B', 'C#', 'D#m', 'Edim'],
            'Gb': ['Gb', 'Abm', 'Bbm', 'Cb', 'Db', 'Ebm', 'Fdim'],
            'Db': ['Db', 'Ebm', 'Fm', 'Gb', 'Ab', 'Bbm', 'Cdim'],
            'Ab': ['Ab', 'Bbm', 'Cm', 'Db', 'Eb', 'Fm', 'Gdim'],
            'Eb': ['Eb', 'Fm', 'Gm', 'Ab', 'Bb', 'Cm', 'Ddim'],
            'Bb': ['Bb', 'Cm', 'Dm', 'Eb', 'F', 'Gm', 'Adim'],
            'F': ['F', 'Gm', 'Am', 'Bb', 'C', 'Dm', 'Edim']
        }
        
        key_root = key[0].upper()
        if key_root in major_chords:
            chords = major_chords[key_root]
            for i, chord in enumerate(chords):
                if chord.startswith(root):
                    degrees = ["主和弦", "上主和弦", "中音和弦", "下属和弦", 
                               "属和弦", "下中音和弦", "导音和弦"]
                    return f"{i+1}级 {degrees[i]}"
        
        return "未知级数"
    
    def format_time(self, seconds):
        """格式化时间为MM:SS"""
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        return f"{minutes:02d}:{seconds:02d}"
    
    def update_performance_data(self):
        """更新性能数据"""
        try:
            if self.start_time and self.is_playing and not self.playback_complete:
                elapsed = time.time() - self.start_time
                throughput = self.message_count / elapsed if elapsed > 0 else 0
                
                # 计算平均延迟
                if self.queue_lengths:
                    self.average_latency = sum(self.queue_lengths) / len(self.queue_lengths)
                else:
                    self.average_latency = 0
                
                performance_data = {
                    'message_count': self.message_count,
                    'session_message_count': self.session_message_count,
                    'throughput': round(throughput, 1),
                    'latency': round(self.average_latency, 2),
                    'active_notes': len(self.active_notes),
                    'queue_size': self.midi_event_queue.qsize(),
                    'active_ports': sum([self.port1_connected, self.port2_connected])
                }
                
                self.update_performance.emit(performance_data)
            else:
                # 不播放时也更新部分性能数据
                performance_data = {
                    'message_count': self.message_count,
                    'session_message_count': self.session_message_count,
                    'throughput': 0,
                    'latency': round(self.average_latency, 2) if self.queue_lengths else 0,
                    'active_notes': len(self.active_notes),
                    'queue_size': self.midi_event_queue.qsize(),
                    'active_ports': sum([self.port1_connected, self.port2_connected])
                }
                self.update_performance.emit(performance_data)
        except Exception as e:
            self.log(f"性能数据更新错误: {str(e)}", "error", is_fatal=False)
    
    def update_realtime_display(self):
        """更新实时显示"""
        try:
            # 确保属性存在
            if not hasattr(self, 'last_display_update'):
                self.last_display_update = time.time()
            if not hasattr(self, 'last_display_count'):
                self.last_display_count = 0
                
            with self.counter_lock:
                current_count = self.message_count
                
            # 计算实时吞吐量
            current_time = time.time()
            elapsed = current_time - self.last_display_update
            
            if elapsed > 0:
                diff = current_count - self.last_display_count
                throughput = diff / elapsed
                
                # 更新实时信息
                memory_usage = psutil.Process().memory_info().rss / (1024 * 1024)
                
                display_text = (f"吞吐量: {throughput:.0f} ev/s | "
                               f"延迟: {self.average_latency:.1f} ms")
                self.performance_info.setText(display_text)
                
                self.last_display_count = current_count
                self.last_display_update = current_time
                
        except Exception as e:
            if self.debug_mode:
                self.log(f"实时显示更新错误: {str(e)}", "error")
    
    def update_fps_counter(self):
        """更新FPS计数器"""
        try:
            current_time = time.time()
            elapsed = current_time - self.fps_last_time
            
            if elapsed > 0:
                fps = self.fps_counter / elapsed
                self.update_fps.emit(int(fps))
            
            self.fps_counter = 0
            self.fps_last_time = current_time
        except Exception as e:
            self.log(f"FPS更新错误: {str(e)}", "error", is_fatal=False)
    
    def show_float_notes_window(self):
        """显示浮动音符窗口"""
        try:
            self.float_window = FloatNotesWindow(self)
            self.float_window.show()
        except Exception as e:
            self.log(f"显示浮动窗口错误: {str(e)}", "error", is_fatal=False)
    
    def log(self, message, level='info', is_fatal=True):
        """记录日志"""
        # 如果是非致命错误且用户选择忽略，则不记录
        if level == 'error' and not is_fatal and hasattr(self, 'ignore_non_fatal_check') and self.ignore_non_fatal_check.isChecked():
            return
            
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        log_entry = f"[{timestamp}] [{level.upper()}] {message}"
        self.update_log.emit(log_entry, level)
    
    @pyqtSlot(str, str)
    def on_status_updated(self, status_text, color):
        """状态更新槽函数"""
        try:
            self.playback_status.setText(f"状态: {status_text}")
            self.playback_status.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 11pt;")
            self.fps_counter += 1
        except Exception as e:
            self.log(f"状态更新错误: {str(e)}", "error", is_fatal=False)
    
    @pyqtSlot(int, int, str)
    def on_progress_updated(self, value, maximum, time_text):
        """进度更新槽函数"""
        try:
            self.progress_bar.setValue(value)
            self.time_label.setText(time_text)
            self.fps_counter += 1
        except Exception as e:
            self.log(f"进度更新错误: {str(e)}", "error", is_fatal=False)
    
    @pyqtSlot(list)
    def on_active_notes_updated(self, notes):
        """活跃音符更新槽函数"""
        try:
            if not self.show_active_notes:
                self.active_notes_table.setRowCount(0)
                return
                
            self.active_notes_table.setRowCount(0)
            
            for note_data in notes:
                row_position = self.active_notes_table.rowCount()
                self.active_notes_table.insertRow(row_position)
                
                self.active_notes_table.setItem(row_position, 0, QTableWidgetItem(note_data['name']))
                self.active_notes_table.setItem(row_position, 1, QTableWidgetItem(str(note_data['octave'])))
                self.active_notes_table.setItem(row_position, 2, QTableWidgetItem(f"{note_data['frequency']} Hz"))
                self.active_notes_table.setItem(row_position, 3, QTableWidgetItem(str(note_data['velocity'])))
                self.active_notes_table.setItem(row_position, 4, QTableWidgetItem(f"{note_data['duration']} s"))
            
            # 更新浮动窗口（如果存在）
            if hasattr(self, 'float_window') and self.float_window.isVisible():
                self.float_window.update_notes(notes)
                
            self.fps_counter += 1
        except Exception as e:
            self.log(f"活跃音符更新错误: {str(e)}", "error", is_fatal=False)
    
    @pyqtSlot(dict)
    def on_performance_updated(self, data):
        """性能数据更新槽函数"""
        try:
            self.msg_count_label.setText(str(data['message_count']))
            self.throughput_label.setText(f"{data['throughput']} msg/s")
            self.latency_label.setText(f"{data['latency']} ms")
            self.active_count_label.setText(str(data['active_notes']))
            self.queue_label.setText(str(data['queue_size']))
            self.active_ports_label.setText(str(data['active_ports']))
            
            self.fps_counter += 1
        except Exception as e:
            self.log(f"性能数据显示错误: {str(e)}", "error", is_fatal=False)
    
    @pyqtSlot(list)
    def on_note_history_updated(self, history):
        """音符历史更新槽函数"""
        try:
            self.note_history_list.clear()
            
            for item in history:
                if item['type'] == 'ON':
                    text = f"{item['time']} - {item['name']}{item['octave']} (ON, Vel: {item['velocity']})"
                else:
                    text = f"{item['time']} - {item['name']}{item['octave']} (OFF, Dur: {item['duration']}s)"
                
                list_item = QListWidgetItem(text)
                self.note_history_list.addItem(list_item)
            
            self.fps_counter += 1
        except Exception as e:
            self.log(f"音符历史更新错误: {str(e)}", "error", is_fatal=False)
    
    @pyqtSlot(str, str)
    def on_log_updated(self, message, level):
        """日志更新槽函数"""
        try:
            # 根据级别设置颜色
            color_codes = {
                'debug': '#888888',
                'info': '#61c0bf',
                'warning': '#ffc107',
                'error': '#dc3545'
            }
            
            # 检查是否需要显示
            show = False
            if level == 'debug' and self.debug_check.isChecked():
                show = True
            elif level == 'info' and self.info_check.isChecked():
                show = True
            elif level == 'warning' and self.warning_check.isChecked():
                show = True
            elif level == 'error' and self.error_check.isChecked():
                show = True
            
            if show:
                self.log_text.setTextColor(QColor(color_codes.get(level, '#ffffff')))
                self.log_text.append(message)
                # 移动到末尾
                cursor = self.log_text.textCursor()
                cursor.movePosition(cursor.MoveOperation.End)
                self.log_text.setTextCursor(cursor)
            
            self.fps_counter += 1
        except Exception as e:
            # 避免日志更新本身出错导致无限循环
            print(f"日志显示错误: {str(e)}")
    
    @pyqtSlot(int, bool)
    def on_port_status_updated(self, port_num, connected):
        """端口状态更新槽函数"""
        try:
            if port_num == 1:
                if connected:
                    self.port1_status.setText("已连接")
                    self.port1_status.setStyleSheet("color: #28a745; font-weight: bold;")
                    self.port1_btn.setText("断开")
                else:
                    self.port1_status.setText("未连接")
                    self.port1_status.setStyleSheet("color: #dc3545; font-weight: bold;")
                    self.port1_btn.setText("连接")
            else:
                if connected:
                    self.port2_status.setText("已连接")
                    self.port2_status.setStyleSheet("color: #28a745; font-weight: bold;")
                    self.port2_btn.setText("断开")
                else:
                    self.port2_status.setText("未连接")
                    self.port2_status.setStyleSheet("color: #dc3545; font-weight: bold;")
                    self.port2_btn.setText("连接")
            
            self.fps_counter += 1
        except Exception as e:
            self.log(f"端口状态更新错误: {str(e)}", "error", is_fatal=False)
    
    @pyqtSlot(list)
    def on_file_list_updated(self, file_list):
        """文件列表更新槽函数"""
        try:
            self.file_list.clear()
            for file_path in file_list:
                self.file_list.addItem(os.path.basename(file_path))
            
            self.fps_counter += 1
        except Exception as e:
            self.log(f"文件列表更新错误: {str(e)}", "error", is_fatal=False)
    
    @pyqtSlot(int)
    def on_fps_updated(self, fps):
        """FPS更新槽函数"""
        try:
            self.fps_label.setText(f"{fps}")
        except Exception as e:
            self.log(f"FPS显示错误: {str(e)}", "error", is_fatal=False)
    
    @pyqtSlot(str)
    def on_music_theory_updated(self, text):
        """乐理知识更新槽函数"""
        try:
            self.theory_text.setPlainText(text)
            self.fps_counter += 1
        except Exception as e:
            self.log(f"乐理知识更新错误: {str(e)}", "error", is_fatal=False)
    
    def closeEvent(self, event: QCloseEvent):
        """关闭事件处理"""
        # 停止所有播放
        self.stop_playback()
        
        # 断开所有端口连接
        self.disconnect_port(1)
        self.disconnect_port(2)
        
        # 设置停止事件
        self.stop_event.set()
        
        # 等待线程结束
        time.sleep(0.1)
        
        event.accept()


class FloatNotesWindow(QMainWindow):
    """浮动音符窗口 - 标准窗口样式"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 设置窗口属性 - 标准窗口样式
        self.setWindowTitle("浮动复音信息")
        self.setGeometry(100, 100, 450, 350)
        self.setMinimumSize(350, 250)
        
        # 设置窗口样式 - 与主窗口协调
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2d2d2d;
                color: #ffffff;
            }
            
            QWidget {
                background-color: #2d2d2d;
                color: #ffffff;
            }
            
            QTableWidget {
                background-color: #2d2d2d;
                color: #ffffff;
                border: 2px solid #61c0bf;
                border-radius: 8px;
                gridline-color: #444444;
                font-size: 10pt;
            }
            
            QTableWidget::header {
                background-color: #61c0bf;
                color: #1a1a1a;
                font-weight: bold;
                border-radius: 4px;
                font-size: 10pt;
            }
            
            QTableWidget::item {
                text-align: center;
                padding: 4px;
                color: #ffffff;
            }
            
            QLabel {
                color: #ffffff;
                font-size: 10pt;
            }
        """)
        
        # 中央窗口
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 布局
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(15, 15, 15, 15)
        layout.setSpacing(10)
        
        # 标题
        title_label = QLabel("活跃音符信息")
        title_label.setStyleSheet("font-weight: bold; font-size: 14pt; color: #ffffff; margin-bottom: 10px;")
        layout.addWidget(title_label)
        
        # 音符表格
        self.notes_table = QTableWidget()
        self.notes_table.setColumnCount(5)
        self.notes_table.setHorizontalHeaderLabels(["音符", "八度", "频率", "力度", "时长"])
        self.notes_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.notes_table)
        
        # 提示信息
        hint_label = QLabel("提示：可通过标题栏拖动窗口，支持大小调整")
        hint_label.setStyleSheet("font-size: 9pt; color: #888888; margin-top: 8px;")
        layout.addWidget(hint_label)
        
        # 连接父窗口的信号
        if parent:
            parent.update_active_notes.connect(self.update_notes)
    
    def update_notes(self, notes):
        """更新音符显示"""
        try:
            self.notes_table.setRowCount(0)
            
            for note_data in notes:
                row_position = self.notes_table.rowCount()
                self.notes_table.insertRow(row_position)
                
                # 所有文字都是白色，与暗色主题协调
                item_note = QTableWidgetItem(note_data['name'])
                item_note.setForeground(QColor("#ffffff"))
                self.notes_table.setItem(row_position, 0, item_note)
                
                item_octave = QTableWidgetItem(str(note_data['octave']))
                item_octave.setForeground(QColor("#ffffff"))
                self.notes_table.setItem(row_position, 1, item_octave)
                
                item_freq = QTableWidgetItem(f"{note_data['frequency']} Hz")
                item_freq.setForeground(QColor("#ffffff"))
                self.notes_table.setItem(row_position, 2, item_freq)
                
                item_vel = QTableWidgetItem(str(note_data['velocity']))
                item_vel.setForeground(QColor("#ffffff"))
                self.notes_table.setItem(row_position, 3, item_vel)
                
                item_dur = QTableWidgetItem(f"{note_data['duration']} s")
                item_dur.setForeground(QColor("#ffffff"))
                self.notes_table.setItem(row_position, 4, item_dur)
        except Exception as e:
            print(f"浮动窗口更新错误: {str(e)}")
    
    def closeEvent(self, event):
        """关闭事件处理"""
        # 可以在这里添加清理代码
        event.accept()


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    # 设置应用程序样式
    app.setStyle("Fusion")
    
    window = MidiPlayerApp()
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
