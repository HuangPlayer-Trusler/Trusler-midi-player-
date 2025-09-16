import sys
import os
import time
import queue
import threading
from collections import deque

import mido
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QGridLayout, QLabel, QPushButton, QComboBox, QListWidget, 
                             QTableWidget, QTableWidgetItem, QTextEdit, QProgressBar,
                             QGroupBox, QFileDialog, QMessageBox, QHeaderView, QCheckBox,
                             QToolButton)
from PyQt6.QtCore import (Qt, pyqtSignal, pyqtSlot, QTimer)
from PyQt6.QtGui import (QColor, QIcon, QTextCursor)

class FloatingHarmonyWindow(QMainWindow):
    """浮动复音信息窗口"""
    closed = pyqtSignal()
    
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("浮动复音信息")
        self.setGeometry(200, 200, 400, 300)
        
        # 主窗口引用
        self.main_window = parent
        
        # 创建表格
        self.harmony_table = QTableWidget()
        self.harmony_table.setColumnCount(5)
        self.harmony_table.setHorizontalHeaderLabels(['持续时间(ms)', '频率(Hz)', '音符', '八度', '力度'])
        self.harmony_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        # 设置样式
        self.harmony_table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                gridline-color: #dddddd;
                border: 1px solid #cccccc;
                font-size: 10pt;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                border: 1px solid #cccccc;
                padding: 6px;
                text-align: center;
                font-weight: bold;
                font-size: 9pt;
            }
            QTableWidget::item {
                padding: 4px;
                text-align: center;
            }
        """)
        
        self.setCentralWidget(self.harmony_table)
        
        # 连接主窗口的信号
        if self.main_window:
            self.main_window.update_harmony_table.connect(self.update_table)
            self.main_window.clear_harmony_table.connect(self.clear_table)
    
    def update_table(self, data):
        """更新表格数据"""
        self.harmony_table.setRowCount(0)
        for row_idx, row_data in enumerate(data):
            self.harmony_table.insertRow(row_idx)
            for col_idx, (key, value) in enumerate(row_data.items()):
                item = QTableWidgetItem(value)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.harmony_table.setItem(row_idx, col_idx, item)
    
    def clear_table(self):
        """清空表格"""
        self.harmony_table.setRowCount(0)
    
    def closeEvent(self, event):
        """关闭事件"""
        self.closed.emit()
        event.accept()

class MIDIVirtualPlayer(QMainWindow):
    # 信号定义
    update_status = pyqtSignal(str, QColor)
    update_harmony_table = pyqtSignal(list)
    update_theory_text = pyqtSignal(str)
    update_history_list = pyqtSignal(list)
    update_progress = pyqtSignal(int, str)
    update_performance = pyqtSignal(str, float)
    update_log = pyqtSignal(str, str)
    clear_harmony_table = pyqtSignal()

    def __init__(self):
        super().__init__()
        # 配色方案
        self.colors = {
            'primary': QColor(234, 188, 221),    # #EABCDD
            'secondary': QColor(240, 223, 234),  # #F0DFEA
            'background': QColor(247, 246, 245), # #F7F6F5
            'accent1': QColor(221, 209, 233),    # #DDD1E9
            'accent2': QColor(164, 181, 213),    # #A4B5D5
            'text': QColor(60, 60, 60),          # 深灰色文本
            'highlight': QColor(140, 160, 195),  # 按钮高亮色
        }
        
        self.setWindowTitle("midi虚拟接口输出 v0.0.2(GUI Mode)")
        self.setGeometry(100, 100, 1200, 750)
        
        # 浮动窗口
        self.floating_harmony_window = None
        
        # 初始化
        self.init_attributes()
        self.precompute_note_info()
        self.setup_ui()
        self.setup_signals()
        self.start_threads()
        
        # 启动定时器
        self.ui_timer = QTimer()
        self.ui_timer.setInterval(1)
        self.ui_timer.timeout.connect(self.process_ui_queue)
        self.ui_timer.start()
        
        self.perf_timer = QTimer()
        self.perf_timer.setInterval(10)
        self.perf_timer.timeout.connect(self.update_performance_data)
        self.perf_timer.start()
        
        # 进度更新定时器
        self.progress_timer = QTimer()
        self.progress_timer.setInterval(50)
        self.progress_timer.timeout.connect(self.update_progress_display)
        self.progress_timer.start()
        
        self.update_status.emit("就绪 - 请添加MIDI文件并连接端口", self.colors['accent2'])

    def init_attributes(self):
        # 核心状态
        self.midi_files = []
        self.current_file_index = -1
        self.is_playing = False
        self.is_paused = False
        self.output_ports = [None, None]
        self.play_start_time = None
        self.total_file_duration = 0
        self.current_play_time = 0.0
        self.message_count = 0
        self.last_perf_update = time.time()
        self.last_message_count = 0
        self.total_latency = 0.0
        self.latency_count = 0
        
        # 当前播放的MIDI文件
        self.current_midi_file = None
        
        # 音符追踪
        self.active_notes = dict()
        self.note_history = deque(maxlen=50)
        
        # 控制事件
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.quit_event = threading.Event()
        
        # 队列
        self.play_queue = queue.Queue(maxsize=5)
        self.midi_event_queue = queue.Queue(maxsize=500)
        self.note_info_queue = queue.Queue(maxsize=50)
        self.ui_queue = queue.Queue(maxsize=200)
        
        # 线程
        self.threads = {}
        
        # 日志级别
        self.log_levels = {'DEBUG': False, 'INFO': True, 'WARN': True, 'ERROR': True}

    def precompute_note_info(self):
        self.note_info_cache = {}
        note_names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
        
        for midi_note in range(128):
            octave = (midi_note // 12) - 1
            note_index = midi_note % 12
            note_name = f"{note_names[note_index]}{octave}"
            frequency = 440.0 * (2.0 ** ((midi_note - 69) / 12.0))
            
            self.note_info_cache[midi_note] = {
                'name': note_name,
                'note_letter': note_names[note_index],
                'octave': octave,
                'frequency': frequency,
                'midi_note': midi_note,
                'note_index': note_index
            }

    def setup_ui(self):
        # 中央窗口
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(8, 8, 8, 8)
        main_layout.setSpacing(8)
        
        # 添加水印文字
        self.watermark_label = QLabel("Trusler")
        self.watermark_label.setStyleSheet("""
            font-size: 10pt;
            color: rgba(128, 128, 128, 50);
            font-weight: bold;
            padding: 4px;
        """)
        self.watermark_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop)
        
        # 创建一个包含水印和其他内容的布局
        top_container = QWidget()
        top_layout = QVBoxLayout(top_container)
        top_layout.setContentsMargins(0, 0, 0, 0)
        top_layout.setSpacing(0)
        
        # 添加水印到顶部
        top_layout.addWidget(self.watermark_label)
        
        # 顶部工具栏
        toolbar_layout = QHBoxLayout()
        top_layout.addLayout(toolbar_layout)
        
        # MIDI端口配置
        port_layout = QHBoxLayout()
        port_layout.setSpacing(15)
        
        # 端口1
        port1_layout = QVBoxLayout()
        port1_layout.setContentsMargins(0, 0, 0, 0)
        port1_layout.setSpacing(4)
        
        self.port1_label = QLabel("端口1:")
        self.port1_label.setStyleSheet("font-size: 11pt; font-weight: bold;")
        
        port1_combo_layout = QHBoxLayout()
        port1_combo_layout.setSpacing(6)
        
        self.port1_combo = QComboBox()
        self.port1_combo.setFixedWidth(150)
        self.port1_combo.setStyleSheet("font-size: 10pt;")
        
        self.connect1_btn = QPushButton("连接")
        self.connect1_btn.setFixedSize(60, 28)
        self.connect1_btn.setStyleSheet("font-size: 10pt; padding: 4px;")
        
        self.port1_status = QLabel("未连接")
        self.port1_status.setStyleSheet("font-size: 9pt; color: red; font-weight: bold;")
        
        port1_combo_layout.addWidget(self.port1_combo)
        port1_combo_layout.addWidget(self.connect1_btn)
        
        port1_layout.addWidget(self.port1_label)
        port1_layout.addLayout(port1_combo_layout)
        port1_layout.addWidget(self.port1_status)
        
        # 端口2
        port2_layout = QVBoxLayout()
        port2_layout.setContentsMargins(0, 0, 0, 0)
        port2_layout.setSpacing(4)
        
        self.port2_label = QLabel("端口2:")
        self.port2_label.setStyleSheet("font-size: 11pt; font-weight: bold;")
        
        port2_combo_layout = QHBoxLayout()
        port2_combo_layout.setSpacing(6)
        
        self.port2_combo = QComboBox()
        self.port2_combo.setFixedWidth(150)
        self.port2_combo.setStyleSheet("font-size: 10pt;")
        
        self.connect2_btn = QPushButton("连接")
        self.connect2_btn.setFixedSize(60, 28)
        self.connect2_btn.setStyleSheet("font-size: 10pt; padding: 4px;")
        
        self.port2_status = QLabel("未连接")
        self.port2_status.setStyleSheet("font-size: 9pt; color: red; font-weight: bold;")
        
        port2_combo_layout.addWidget(self.port2_combo)
        port2_combo_layout.addWidget(self.connect2_btn)
        
        port2_layout.addWidget(self.port2_label)
        port2_layout.addLayout(port2_combo_layout)
        port2_layout.addWidget(self.port2_status)
        
        # 测试按钮
        self.test_btn = QPushButton("测试连接")
        self.test_btn.setFixedSize(100, 30)
        self.test_btn.setStyleSheet("font-size: 10pt; padding: 4px;")
        self.test_btn.setEnabled(False)
        
        # 状态显示
        self.status_label = QLabel("就绪 - 请添加MIDI文件并连接端口")
        self.status_label.setStyleSheet("font-size: 11pt; font-weight: bold; color: #4A90E2;")
        self.status_label.setFixedWidth(400)
        
        port_layout.addLayout(port1_layout)
        port_layout.addLayout(port2_layout)
        port_layout.addWidget(self.test_btn)
        port_layout.addWidget(self.status_label)
        port_layout.addStretch()
        
        toolbar_layout.addLayout(port_layout)
        
        main_layout.addWidget(top_container)
        
        # 文件管理和播放控制
        file_control_layout = QHBoxLayout()
        main_layout.addLayout(file_control_layout)
        
        # 文件管理
        file_group = QGroupBox("文件管理")
        file_group.setStyleSheet("font-size: 11pt; font-weight: bold;")
        file_layout = QVBoxLayout(file_group)
        file_layout.setContentsMargins(6, 6, 6, 6)
        file_layout.setSpacing(6)
        
        file_btn_layout = QHBoxLayout()
        file_btn_layout.setSpacing(6)
        
        self.add_btn = QPushButton("添加文件")
        self.add_btn.setFixedSize(80, 30)
        self.add_btn.setStyleSheet("font-size: 10pt; padding: 4px;")
        
        self.remove_btn = QPushButton("移除选中")
        self.remove_btn.setFixedSize(80, 30)
        self.remove_btn.setStyleSheet("font-size: 10pt; padding: 4px;")
        
        self.clear_btn = QPushButton("清空列表")
        self.clear_btn.setFixedSize(80, 30)
        self.clear_btn.setStyleSheet("font-size: 10pt; padding: 4px;")
        
        file_btn_layout.addWidget(self.add_btn)
        file_btn_layout.addWidget(self.remove_btn)
        file_btn_layout.addWidget(self.clear_btn)
        
        self.file_list = QListWidget()
        self.file_list.setFixedHeight(80)
        self.file_list.setStyleSheet("font-size: 10pt;")
        
        file_layout.addLayout(file_btn_layout)
        file_layout.addWidget(self.file_list)
        
        # 播放控制
        control_group = QGroupBox("播放控制")
        control_group.setStyleSheet("font-size: 11pt; font-weight: bold;")
        control_layout = QVBoxLayout(control_group)
        control_layout.setContentsMargins(6, 6, 6, 6)
        control_layout.setSpacing(6)
        
        # 播放按钮
        play_btn_layout = QHBoxLayout()
        play_btn_layout.setSpacing(8)
        
        self.play_btn = QPushButton("播放")
        self.play_btn.setFixedSize(70, 32)
        self.play_btn.setStyleSheet("font-size: 11pt; padding: 4px;")
        
        self.stop_btn = QPushButton("停止")
        self.stop_btn.setFixedSize(70, 32)
        self.stop_btn.setStyleSheet("font-size: 11pt; padding: 4px;")
        self.stop_btn.setEnabled(False)
        
        self.prev_btn = QPushButton("上一首")
        self.prev_btn.setFixedSize(70, 32)
        self.prev_btn.setStyleSheet("font-size: 10pt; padding: 4px;")
        
        self.next_btn = QPushButton("下一首")
        self.next_btn.setFixedSize(70, 32)
        self.next_btn.setStyleSheet("font-size: 10pt; padding: 4px;")
        
        play_btn_layout.addWidget(self.play_btn)
        play_btn_layout.addWidget(self.stop_btn)
        play_btn_layout.addWidget(self.prev_btn)
        play_btn_layout.addWidget(self.next_btn)
        
        # 进度条（仅显示，不可点击）
        progress_layout = QHBoxLayout()
        progress_layout.setSpacing(8)
        
        self.progress_label = QLabel("00:00 / 00:00")
        self.progress_label.setStyleSheet("font-size: 10pt; font-weight: bold;")
        self.progress_label.setFixedWidth(100)
        
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #f0f0f0;
                border: 1px solid #cccccc;
                border-radius: 9px;
                text-align: center;
                font-size: 9pt;
                font-weight: bold;
            }
            QProgressBar::chunk {
                background-color: #4CAF50;
                border-radius: 8px;
            }
        """)
        self.progress_bar.setCursor(Qt.CursorShape.ArrowCursor)  # 设置为普通光标
        
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar)
        
        control_layout.addLayout(play_btn_layout)
        control_layout.addLayout(progress_layout)
        
        file_control_layout.addWidget(file_group, stretch=1)
        file_control_layout.addWidget(control_group, stretch=3)
        
        # 主要信息区域
        info_layout = QHBoxLayout()
        main_layout.addLayout(info_layout, stretch=2)
        
        # 左侧：复音信息和性能监控
        left_info_layout = QVBoxLayout()
        
        # 复音信息（带浮动按钮）
        harmony_container = QWidget()
        harmony_layout = QHBoxLayout(harmony_container)
        harmony_layout.setContentsMargins(0, 0, 0, 0)
        harmony_layout.setSpacing(2)
        
        harmony_group = QGroupBox("复音信息")
        harmony_group.setStyleSheet("font-size: 11pt; font-weight: bold;")
        harmony_inner_layout = QVBoxLayout(harmony_group)
        harmony_inner_layout.setContentsMargins(6, 6, 6, 6)
        
        # 浮动窗口按钮
        self.float_btn = QToolButton()
        self.float_btn.setIcon(QIcon.fromTheme("window-new"))
        self.float_btn.setToolTip("浮动窗口")
        self.float_btn.setFixedSize(24, 24)
        self.float_btn.setStyleSheet("font-size: 8pt;")
        
        self.harmony_table = QTableWidget()
        self.harmony_table.setColumnCount(5)
        self.harmony_table.setHorizontalHeaderLabels(['持续时间(ms)', '频率(Hz)', '音符', '八度', '力度'])
        self.harmony_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.harmony_table.setFixedHeight(120)
        self.harmony_table.setStyleSheet("""
            QTableWidget {
                background-color: white;
                gridline-color: #dddddd;
                border: 1px solid #cccccc;
                font-size: 10pt;
            }
            QHeaderView::section {
                background-color: #f0f0f0;
                border: 1px solid #cccccc;
                padding: 6px;
                text-align: center;
                font-weight: bold;
                font-size: 9pt;
            }
            QTableWidget::item {
                padding: 4px;
                text-align: center;
            }
        """)
        
        harmony_inner_layout.addWidget(self.harmony_table)
        harmony_layout.addWidget(harmony_group)
        harmony_layout.addWidget(self.float_btn)
        
        # 性能监控
        perf_group = QGroupBox("实时性能监控 (10ms更新)")
        perf_group.setStyleSheet("font-size: 11pt; font-weight: bold;")
        perf_layout = QGridLayout(perf_group)
        perf_layout.setContentsMargins(6, 6, 6, 6)
        perf_layout.setSpacing(6)
        perf_layout.setColumnStretch(0, 1)
        perf_layout.setColumnStretch(1, 1)
        
        # 性能指标标签
        self.msg_count_label = QLabel("消息计数: 0")
        self.throughput_label = QLabel("吞吐量: 0.0 msg/s")
        self.latency_label = QLabel("平均延迟: 0.00 ms")
        self.active_count_label = QLabel("活跃音符: 0")
        self.queue_label = QLabel("队列: 0/500 (0%)")
        self.port_label = QLabel("活跃端口: 0")
        
        # 设置性能标签样式
        perf_labels = [self.msg_count_label, self.throughput_label, self.latency_label, 
                      self.active_count_label, self.queue_label, self.port_label]
        for label in perf_labels:
            label.setStyleSheet("font-family: Consolas; font-size: 10pt; font-weight: bold;")
        
        # 网格布局排列
        perf_layout.addWidget(self.msg_count_label, 0, 0)
        perf_layout.addWidget(self.throughput_label, 0, 1)
        perf_layout.addWidget(self.latency_label, 1, 0)
        perf_layout.addWidget(self.active_count_label, 1, 1)
        perf_layout.addWidget(self.queue_label, 2, 0)
        perf_layout.addWidget(self.port_label, 2, 1)
        
        left_info_layout.addWidget(harmony_container)
        left_info_layout.addWidget(perf_group)
        
        # 右侧：乐理知识和历史记录
        right_info_layout = QVBoxLayout()
        
        # 乐理知识
        theory_group = QGroupBox("乐理知识")
        theory_group.setStyleSheet("font-size: 11pt; font-weight: bold;")
        theory_layout = QVBoxLayout(theory_group)
        theory_layout.setContentsMargins(6, 6, 6, 6)
        
        self.theory_text = QTextEdit()
        self.theory_text.setReadOnly(True)
        self.theory_text.setFixedHeight(100)
        self.theory_text.setStyleSheet("font-size: 10pt; line-height: 1.4;")
        self.theory_text.setText("等待音符播放...")
        
        theory_layout.addWidget(self.theory_text)
        
        # 历史记录
        history_group = QGroupBox("音符历史")
        history_group.setStyleSheet("font-size: 11pt; font-weight: bold;")
        history_layout = QVBoxLayout(history_group)
        history_layout.setContentsMargins(6, 6, 6, 6)
        
        self.history_list = QListWidget()
        self.history_list.setFixedHeight(140)
        self.history_list.setStyleSheet("font-size: 9pt; font-family: Consolas;")
        
        history_layout.addWidget(self.history_list)
        
        right_info_layout.addWidget(theory_group)
        right_info_layout.addWidget(history_group)
        
        info_layout.addLayout(left_info_layout, stretch=2)
        info_layout.addLayout(right_info_layout, stretch=1)
        
        # 日志区域
        log_group = QGroupBox("系统日志")
        log_group.setStyleSheet("font-size: 11pt; font-weight: bold;")
        log_layout = QHBoxLayout(log_group)
        log_layout.setContentsMargins(6, 6, 6, 6)
        log_layout.setSpacing(6)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFixedHeight(100)
        self.log_text.setStyleSheet("font-family: Consolas; font-size: 9pt;")
        
        # 日志过滤器
        filter_layout = QVBoxLayout()
        filter_layout.setContentsMargins(0, 0, 0, 0)
        filter_layout.setSpacing(4)
        
        filter_label = QLabel("日志级别:")
        filter_label.setStyleSheet("font-size: 10pt; font-weight: bold;")
        
        self.debug_check = QCheckBox("调试")
        self.info_check = QCheckBox("信息")
        self.warn_check = QCheckBox("警告")
        self.error_check = QCheckBox("错误")
        
        # 设置复选框样式
        checkboxes = [self.debug_check, self.info_check, self.warn_check, self.error_check]
        for cb in checkboxes:
            cb.setStyleSheet("font-size: 10pt;")
            cb.setFixedSize(60, 20)
        
        self.info_check.setChecked(True)
        self.warn_check.setChecked(True)
        self.error_check.setChecked(True)
        
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.debug_check)
        filter_layout.addWidget(self.info_check)
        filter_layout.addWidget(self.warn_check)
        filter_layout.addWidget(self.error_check)
        filter_layout.addStretch()
        
        log_layout.addWidget(self.log_text)
        log_layout.addLayout(filter_layout)
        
        main_layout.addWidget(log_group)
        
        # 设置整体样式
        self.setStyleSheet(self.get_stylesheet())
        
        # 检测MIDI端口
        self.detect_midi_ports()

    def get_stylesheet(self):
        """生成完整样式表"""
        return f"""
        QWidget {{
            background-color: {self.colors['background'].name()};
            color: {self.colors['text'].name()};
            font-family: "Segoe UI", Arial, sans-serif;
            font-size: 10pt;
        }}
        QGroupBox {{
            background-color: {self.colors['secondary'].name()};
            border: 1px solid {self.colors['accent1'].name()};
            border-radius: 6px;
            margin-top: 8px;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 8px;
            padding: 0 4px 0 4px;
            color: {self.colors['text'].name()};
            font-weight: bold;
        }}
        QPushButton {{
            background-color: {self.colors['accent2'].name()};
            color: white;
            border: none;
            padding: 6px 12px;
            border-radius: 4px;
            font-weight: bold;
        }}
        QPushButton:hover {{
            background-color: {self.colors['highlight'].name()};
        }}
        QPushButton:disabled {{
            background-color: #cccccc;
            color: #666666;
        }}
        QToolButton {{
            background-color: {self.colors['accent1'].name()};
            color: {self.colors['text'].name()};
            border: none;
            border-radius: 3px;
        }}
        QToolButton:hover {{
            background-color: {self.colors['accent2'].name()};
            color: white;
        }}
        QComboBox {{
            background-color: white;
            border: 1px solid {self.colors['accent1'].name()};
            border-radius: 4px;
            padding: 4px;
        }}
        QListWidget, QTextEdit {{
            background-color: white;
            border: 1px solid {self.colors['accent1'].name()};
            border-radius: 4px;
        }}
        QLabel {{
            color: {self.colors['text'].name()};
        }}
        QCheckBox {{
            spacing: 4px;
        }}
        """

    def setup_signals(self):
        # UI信号连接
        self.connect1_btn.clicked.connect(lambda: self.connect_port(0))
        self.connect2_btn.clicked.connect(lambda: self.connect_port(1))
        self.test_btn.clicked.connect(self.send_test_signal)
        self.add_btn.clicked.connect(self.add_files)
        self.remove_btn.clicked.connect(self.remove_selected)
        self.clear_btn.clicked.connect(self.clear_list)
        self.play_btn.clicked.connect(self.toggle_play)
        self.stop_btn.clicked.connect(self.stop_play)
        self.prev_btn.clicked.connect(self.prev_file)
        self.next_btn.clicked.connect(self.next_file)
        self.float_btn.clicked.connect(self.toggle_floating_harmony_window)
        
        # 过滤器信号
        self.debug_check.stateChanged.connect(self.update_log_levels)
        self.info_check.stateChanged.connect(self.update_log_levels)
        self.warn_check.stateChanged.connect(self.update_log_levels)
        self.error_check.stateChanged.connect(self.update_log_levels)
        
        # 自定义信号连接
        self.update_status.connect(self.on_update_status)
        self.update_harmony_table.connect(self.on_update_harmony_table)
        self.update_theory_text.connect(self.on_update_theory_text)
        self.update_history_list.connect(self.on_update_history_list)
        self.update_progress.connect(self.on_update_progress)
        self.update_performance.connect(self.on_update_performance)
        self.update_log.connect(self.on_update_log)
        self.clear_harmony_table.connect(self.on_clear_harmony_table)

    def start_threads(self):
        # 文件解析线程（直接播放）
        self.threads['file_parser'] = threading.Thread(
            target=self.file_parser_thread,
            daemon=True,
            name="FileParser"
        )
        self.threads['file_parser'].start()
        
        # MIDI发送线程
        self.threads['midi_sender'] = threading.Thread(
            target=self.midi_sender_thread,
            daemon=True,
            name="MIDISender"
        )
        self.threads['midi_sender'].start()
        
        # 音符处理线程
        self.threads['note_processor'] = threading.Thread(
            target=self.note_processor_thread,
            daemon=True,
            name="NoteProcessor"
        )
        self.threads['note_processor'].start()

    def detect_midi_ports(self):
        try:
            ports = mido.get_output_names()
            self.port1_combo.addItems(ports)
            self.port2_combo.addItems(ports)
            
            # 自动选择第一个可用的虚拟端口
            for i, port in enumerate(ports):
                if "Virtual" in port or "LoopMIDI" in port:
                    if self.port1_combo.currentIndex() == -1:
                        self.port1_combo.setCurrentIndex(i)
                    elif self.port2_combo.currentIndex() == -1 and i != self.port1_combo.currentIndex():
                        self.port2_combo.setCurrentIndex(i)
                    if self.port1_combo.currentIndex() != -1 and self.port2_combo.currentIndex() != -1:
                        break
                    
            self.log_message(f"检测到 {len(ports)} 个MIDI输出端口", "INFO")
        except Exception as e:
            self.log_message(f"MIDI端口检测失败: {str(e)}", "ERROR")
            self.update_status.emit("MIDI检测失败", QColor(255, 0, 0))

    def connect_port(self, port_index):
        if port_index not in [0, 1]:
            return
            
        port_combo = self.port1_combo if port_index == 0 else self.port2_combo
        connect_btn = self.connect1_btn if port_index == 0 else self.connect2_btn
        port_status = self.port1_status if port_index == 0 else self.port2_status
        
        port_name = port_combo.currentText()
        if not port_name:
            QMessageBox.warning(self, "警告", f"请选择MIDI端口{port_index + 1}")
            return
            
        try:
            # 检查端口是否已连接
            if self.output_ports[port_index]:
                self.output_ports[port_index].close()
                self.output_ports[port_index] = None
                connect_btn.setText("连接")
                port_status.setText("未连接")
                port_status.setStyleSheet("font-size: 9pt; color: red; font-weight: bold;")
                self.log_message(f"已断开MIDI端口{port_index + 1}: {port_name}", "INFO")
            else:
                # 检查是否与另一个端口冲突
                other_port = self.output_ports[1 - port_index]
                if other_port and other_port.name == port_name:
                    QMessageBox.warning(self, "警告", f"端口{port_name}已被端口{2 - port_index}使用")
                    return
                    
                self.output_ports[port_index] = mido.open_output(port_name, autoreset=True)
                connect_btn.setText("断开")
                port_status.setText(f"已连接")
                port_status.setStyleSheet("font-size: 9pt; color: green; font-weight: bold;")
                self.log_message(f"成功连接到MIDI端口{port_index + 1}: {port_name}", "INFO")
                
            # 更新测试按钮状态和端口计数
            active_ports = len([port for port in self.output_ports if port is not None])
            self.test_btn.setEnabled(active_ports > 0)
            self.port_label.setText(f"活跃端口: {active_ports}")
            
        except Exception as e:
            self.log_message(f"MIDI端口{port_index + 1}连接失败: {str(e)}", "ERROR")
            QMessageBox.critical(self, "错误", f"端口{port_index + 1}连接失败: {str(e)}")

    def send_test_signal(self):
        active_ports = [port for port in self.output_ports if port is not None]
        if not active_ports:
            QMessageBox.warning(self, "警告", "请先连接至少一个MIDI端口")
            return
            
        try:
            chords = [
                ([60, 64, 67], "C大三和弦"),
                ([60, 63, 67], "C小三和弦"),
            ]
            
            for chord_notes, chord_name in chords:
                self.log_message(f"测试播放: {chord_name} (通过{len(active_ports)}个端口)", "INFO")
                
                # 同时发送到所有活跃端口
                for port in active_ports:
                    for note in chord_notes:
                        port.send(mido.Message('note_on', note=note, velocity=64))
                time.sleep(0.001)
                
                time.sleep(0.5)
                
                # 同时关闭所有活跃端口的音符
                for port in active_ports:
                    for note in chord_notes:
                        port.send(mido.Message('note_off', note=note, velocity=64))
                time.sleep(0.001)
                
                time.sleep(0.3)
                
            self.log_message(f"MIDI连接测试成功 - 通过{len(active_ports)}个端口", "INFO")
            self.update_status.emit(f"连接测试成功 (使用{len(active_ports)}个端口)", QColor(0, 255, 0))
        except Exception as e:
            self.log_message(f"测试信号发送失败: {str(e)}", "ERROR")

    def add_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择MIDI文件", "", "MIDI文件 (*.mid *.midi);;所有文件 (*.*)"
        )
        
        if files:
            count = 0
            for file in files:
                if file not in self.midi_files:
                    self.midi_files.append(file)
                    filename = os.path.basename(file)
                    size = os.path.getsize(file)
                    self.file_list.addItem(f"{filename} ({size} bytes)")
                    count += 1
                    
            if count > 0:
                self.log_message(f"添加了 {count} 个MIDI文件", "INFO")
                if len(self.midi_files) == count:
                    self.file_list.setCurrentRow(0)
                    self.current_file_index = 0

    def remove_selected(self):
        selected = self.file_list.currentRow()
        if selected >= 0:
            file = self.midi_files.pop(selected)
            self.file_list.takeItem(selected)
            self.log_message(f"移除文件: {os.path.basename(file)}", "INFO")
            
            if self.current_file_index == selected:
                self.current_file_index = -1
                self.update_status.emit("就绪 - 请选择文件", self.colors['accent2'])
            elif self.current_file_index > selected:
                self.current_file_index -= 1

    def clear_list(self):
        if QMessageBox.question(self, "确认", "确定要清空所有文件吗？") == QMessageBox.StandardButton.Yes:
            self.midi_files.clear()
            self.file_list.clear()
            self.current_file_index = -1
            self.current_midi_file = None
            self.total_file_duration = 0
            self.update_status.emit("就绪 - 请添加MIDI文件", self.colors['accent2'])
            self.log_message("已清空文件列表", "INFO")

    def toggle_play(self):
        active_ports = [port for port in self.output_ports if port is not None]
        if not active_ports:
            QMessageBox.warning(self, "警告", "请至少连接一个MIDI端口")
            return
            
        if not self.midi_files:
            QMessageBox.warning(self, "警告", "请添加MIDI文件")
            return
            
        if self.is_playing:
            if self.is_paused:
                self.resume_play()
            else:
                self.pause_play()
        else:
            self.start_play()

    def start_play(self):
        if self.current_file_index == -1:
            self.current_file_index = 0
            self.file_list.setCurrentRow(self.current_file_index)
            
        if 0 <= self.current_file_index < len(self.midi_files):
            file_path = self.midi_files[self.current_file_index]
            
            try:
                # 直接解析MIDI文件
                self.current_midi_file = mido.MidiFile(file_path)
                # 计算总时长（简化版）
                self.total_file_duration = sum(msg.time for track in self.current_midi_file.tracks for msg in track if not msg.is_meta)
                
            except Exception as e:
                self.log_message(f"解析MIDI文件失败: {str(e)}", "ERROR")
                self.update_status.emit("文件加载失败", QColor(255, 0, 0))
                return
            
            self.is_playing = True
            self.is_paused = False
            self.play_start_time = time.time()
            self.current_play_time = 0.0
            self.message_count = 0
            self.last_message_count = 0
            self.last_perf_update = time.time()
            self.total_latency = 0.0
            self.latency_count = 0
            
            self.stop_event.clear()
            self.pause_event.set()
            
            self.play_btn.setText("暂停")
            self.stop_btn.setEnabled(True)
            
            filename = os.path.basename(file_path)
            active_ports = len([p for p in self.output_ports if p is not None])
            self.update_status.emit(f"正在播放: {filename} (x{active_ports})", QColor(0, 255, 0))
            self.log_message(f"开始播放: {filename}", "INFO")
            
            # 清空队列
            while not self.play_queue.empty():
                try:
                    self.play_queue.get_nowait()
                except queue.Empty:
                    break
                    
            # 开始播放
            self.play_queue.put((file_path, self.current_file_index))

    def pause_play(self):
        self.is_paused = True
        self.pause_event.clear()
        self.play_btn.setText("播放")
        file = os.path.basename(self.midi_files[self.current_file_index])
        self.update_status.emit(f"已暂停: {file}", QColor(255, 165, 0))
        self.log_message("播放已暂停", "INFO")

    def resume_play(self):
        self.is_paused = False
        self.pause_event.set()
        self.play_btn.setText("暂停")
        file = os.path.basename(self.midi_files[self.current_file_index])
        active_ports = len([p for p in self.output_ports if p is not None])
        self.update_status.emit(f"正在播放: {file} (x{active_ports})", QColor(0, 255, 0))
        self.log_message("播放已恢复", "INFO")

    def stop_play(self):
        self.is_playing = False
        self.is_paused = False
        self.play_start_time = None
        self.current_play_time = 0.0
        
        self.stop_event.set()
        self.pause_event.set()
        
        # 清空队列
        while not self.play_queue.empty():
            try:
                self.play_queue.get_nowait()
            except queue.Empty:
                break
                
        while not self.midi_event_queue.empty():
            try:
                self.midi_event_queue.get_nowait()
            except queue.Empty:
                break
                
        self.active_notes.clear()
        self.note_history.clear()
        self.current_midi_file = None
        
        self.play_btn.setText("播放")
        self.stop_btn.setEnabled(False)
        self.clear_harmony_table.emit()
        self.update_history_list.emit([])
        
        # 重置进度条显示
        self.progress_bar.setValue(0)
        self.progress_label.setText("00:00 / 00:00")
        
        # 发送所有音符关闭到所有端口
        self.all_notes_off()
        
        if self.current_file_index >= 0:
            file = os.path.basename(self.midi_files[self.current_file_index])
            self.update_status.emit(f"已停止: {file}", QColor(255, 0, 0))
        else:
            self.update_status.emit("就绪 - 请选择文件", self.colors['accent2'])
            
        self.log_message("播放已停止", "INFO")

    def prev_file(self):
        if self.midi_files:
            self.stop_play()
            self.current_file_index = (self.current_file_index - 1) % len(self.midi_files)
            self.file_list.setCurrentRow(self.current_file_index)
            file = os.path.basename(self.midi_files[self.current_file_index])
            self.update_status.emit(f"准备播放: {file}", self.colors['accent2'])
            self.log_message(f"切换到上一首: {file}", "INFO")

    def next_file(self):
        if self.midi_files:
            self.stop_play()
            self.current_file_index = (self.current_file_index + 1) % len(self.midi_files)
            self.file_list.setCurrentRow(self.current_file_index)
            file = os.path.basename(self.midi_files[self.current_file_index])
            self.update_status.emit(f"准备播放: {file}", self.colors['accent2'])
            self.log_message(f"切换到下一首: {file}", "INFO")

    def file_parser_thread(self):
        """简化的播放线程 - 直接使用mido的play()方法"""
        while not self.quit_event.is_set():
            try:
                file_path, file_index = self.play_queue.get(timeout=0.1)
                
                if self.stop_event.is_set() or file_index != self.current_file_index:
                    self.play_queue.task_done()
                    continue
                    
                try:
                    # 直接使用mido的play()方法播放
                    midi_file = mido.MidiFile(file_path)
                    start_time = time.time()
                    
                    for msg in midi_file.play():
                        if self.stop_event.is_set() or file_index != self.current_file_index:
                            break
                            
                        # 等待暂停状态
                        while self.is_paused and not self.stop_event.is_set():
                            time.sleep(0.001)
                            
                        if self.stop_event.is_set():
                            break
                            
                        # 更新当前播放时间
                        self.current_play_time = time.time() - start_time
                        
                        # 同时发送到所有活跃端口
                        active_ports = [port for port in self.output_ports if port is not None]
                        if active_ports and not msg.is_meta:
                            send_start = time.time()
                            
                            # 发送到所有端口
                            for port in active_ports:
                                port.send(msg)
                                
                            send_end = time.time()
                            latency = (send_end - send_start) * 1000
                            
                            # 更新延迟统计
                            self.total_latency += latency
                            self.latency_count += 1
                            
                            self.message_count += 1
                            
                            # 处理音符消息
                            if msg.type in ['note_on', 'note_off'] and hasattr(msg, 'note'):
                                self.note_info_queue.put((msg.type, msg.note, msg.velocity, send_start, self.current_play_time, self.total_file_duration))
                            
                except Exception as e:
                    self.log_message(f"播放错误: {str(e)}", "ERROR")
                    
                if not self.stop_event.is_set() and file_index == self.current_file_index:
                    self.log_message(f"文件播放完成: {os.path.basename(file_path)}", "INFO")
                    
                    if self.current_file_index < len(self.midi_files) - 1:
                        self.update_status.emit("准备播放下一首", self.colors['accent2'])
                        QTimer.singleShot(1000, self.next_file)
                        QTimer.singleShot(1500, self.toggle_play)
                    else:
                        QTimer.singleShot(1000, self.stop_play)
                        
                self.play_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                self.log_message(f"播放线程错误: {str(e)}", "ERROR")
                time.sleep(0.1)

    def midi_sender_thread(self):
        """这个线程现在主要用于处理音符信息，实际发送由file_parser_thread处理"""
        while not self.quit_event.is_set():
            time.sleep(0.1)

    def note_processor_thread(self):
        while not self.quit_event.is_set():
            try:
                notes_to_process = []
                try:
                    # 批量获取音符事件
                    for _ in range(5):
                        notes_to_process.append(self.note_info_queue.get(timeout=0.001))
                except queue.Empty:
                    pass
                
                if notes_to_process:
                    for msg_type, note, velocity, timestamp, current_time, total_time in notes_to_process:
                        self.process_single_note(msg_type, note, velocity, timestamp, current_time, total_time)
                    
                    self.update_harmony_display()
                    self.update_history_display()
                    
                else:
                    if self.active_notes:
                        self.update_active_notes_duration()
                        self.update_harmony_display()
                        
                    time.sleep(0.001)
                    
            except Exception as e:
                self.log_message(f"音符处理线程错误: {str(e)}", "ERROR")
                time.sleep(0.01)

    def process_single_note(self, msg_type, note, velocity, timestamp, current_time, total_time):
        if msg_type == 'note_on' and velocity > 0:
            note_info = self.note_info_cache.get(note, {
                'name': f"未知({note})",
                'note_letter': f"未知",
                'octave': "--",
                'frequency': 0.0,
                'note_index': -1
            })
            
            self.active_notes[note] = {
                'note_info': note_info,
                'velocity': velocity,
                'start_time': timestamp,
                'current_time': current_time,
                'total_time': total_time
            }
            
            self.note_history.appendleft({
                'type': 'ON',
                'note': note_info['name'],
                'velocity': velocity,
                'time': timestamp
            })
            
        elif msg_type == 'note_off' or (msg_type == 'note_on' and velocity == 0):
            if note in self.active_notes:
                note_data = self.active_notes.pop(note)
                duration = (timestamp - note_data['start_time']) * 1000
                
                for item in self.note_history:
                    if item['type'] == 'ON' and item['note'] == note_data['note_info']['name'] and 'duration' not in item:
                        item['duration'] = duration
                        break
                        
                self.note_history.appendleft({
                    'type': 'OFF',
                    'note': note_data['note_info']['name'],
                    'duration': duration,
                    'time': timestamp
                })

    def update_active_notes_duration(self):
        current_time = time.time()
        for note_data in self.active_notes.values():
            note_data['duration'] = (current_time - note_data['start_time']) * 1000

    def update_harmony_display(self):
        if not self.active_notes:
            self.clear_harmony_table.emit()
            return
            
        display_data = []
        for note_data in sorted(self.active_notes.values(), key=lambda x: x['note_info']['midi_note']):
            duration = (time.time() - note_data['start_time']) * 1000
            display_data.append({
                'note': note_data['note_info']['name'],
                'octave': str(note_data['note_info']['octave']),
                'frequency': f"{note_data['note_info']['frequency']:.0f}",
                'velocity': str(note_data['velocity']),
                'duration': f"{duration:.0f}"
            })
            
        self.update_harmony_table.emit(display_data)
        
        if display_data:
            first_note = display_data[0]['note']
            theory_info = self.get_music_theory_info(first_note)
            self.update_theory_text.emit(theory_info)

    def update_history_display(self):
        history_items = []
        for item in self.note_history:
            ts = time.strftime("%H:%M:%S", time.localtime(item['time']))
            ms = int((item['time'] % 1) * 1000)
            timestamp = f"{ts}.{ms:03d}"
            
            if item['type'] == 'ON':
                dur_text = f",{item['duration']:.0f}ms" if 'duration' in item else ""
                display_text = f"[{timestamp}] 🔊 {item['note']}({item['velocity']}){dur_text}"
            else:
                display_text = f"[{timestamp}] 🔇 {item['note']}({item['duration']:.0f}ms)"
            history_items.append(display_text)
            
        self.update_history_list.emit(history_items)

    def get_music_theory_info(self, note_name):
        if note_name == "--" or note_name == "未知":
            return "等待音符播放..."
            
        note = note_name[:-1]
        octave = note_name[-1]
        
        info = [f"音符: {note}{octave}"]
        
        major_scales = {
            'C': ['C', 'D', 'E', 'F', 'G', 'A', 'B'],
            'G': ['G', 'A', 'B', 'C', 'D', 'E', 'F#'],
            'D': ['D', 'E', 'F#', 'G', 'A', 'B', 'C#'],
            'A': ['A', 'B', 'C#', 'D', 'E', 'F#', 'G#'],
            'F': ['F', 'G', 'A', 'Bb', 'C', 'D', 'E'],
            'Bb': ['Bb', 'C', 'D', 'Eb', 'F', 'G', 'A']
        }
        
        for key, scale in major_scales.items():
            if note in scale:
                position = scale.index(note) + 1
                info.append(f"{key}大调: 第{position}级")
                break
                
        intervals = {
            'C': {'C': '同度', 'D': '大二度', 'E': '大三度', 'F': '纯四度', 'G': '纯五度'},
            'D': {'C': '小七度', 'D': '同度', 'E': '大二度', 'F': '小三度', 'G': '纯四度'},
            'E': {'C': '小六度', 'D': '小七度', 'E': '同度', 'F': '大二度', 'G': '小三度'},
            'F': {'C': '纯五度', 'D': '小六度', 'E': '小七度', 'F': '同度', 'G': '大二度'},
            'G': {'C': '纯四度', 'D': '纯五度', 'E': '小六度', 'F': '小七度', 'G': '同度'},
            'A': {'C': '大三度', 'D': '纯四度', 'E': '纯五度', 'F': '小六度', 'G': '小七度'},
            'B': {'C': '大二度', 'D': '大三度', 'E': '纯四度', 'F': '纯五度', 'G': '小六度'}
        }
        
        if note in intervals and 'C' in intervals[note]:
            info.append(f"与C音程: {intervals[note]['C']}")
            
        if len(self.active_notes) > 1:
            chord_name = self.detect_chord()
            if chord_name:
                info.append(f"和弦: {chord_name}")
                
        return "\n".join(info)

    def detect_chord(self):
        if len(self.active_notes) < 2:
            return ""
            
        note_indices = [data['note_info']['note_index'] for data in self.active_notes.values()]
        note_letters = [data['note_info']['note_letter'] for data in self.active_notes.values()]
        
        unique_indices = sorted(list(set(note_indices)))
        unique_letters = sorted(list(set(note_letters)))
        
        if unique_indices:
            base_index = unique_indices[0]
            interval_pattern = tuple((idx - base_index) % 12 for idx in unique_indices)
            
            chord_patterns = {
                (0, 4, 7, 11): ('大七和弦', 'Maj7'),
                (0, 4, 7, 10): ('属七和弦', '7'),
                (0, 3, 7, 10): ('小七和弦', 'm7'),
                (0, 3, 6, 10): ('半减七和弦', 'm7b5'),
                (0, 3, 6, 9): ('减七和弦', 'dim7'),
                (0, 3, 7, 11): ('小大七和弦', 'mMaj7'),
                
                (0, 4, 7): ('大三和弦', 'Maj'),
                (0, 3, 7): ('小三和弦', 'm'),
                (0, 3, 6): ('减三和弦', 'dim'),
                (0, 4, 8): ('增三和弦', 'aug'),
                
                (0, 5, 7): ('挂四和弦', 'sus4'),
                (0, 2, 7): ('挂二和弦', 'sus2'),
                
                (0, 4, 7, 9): ('加九和弦', 'add9'),
                (0, 3, 7, 9): ('小加九和弦', 'madd9'),
                (0, 4, 7, 6): ('加六和弦', 'add6'),
            }
            
            if interval_pattern in chord_patterns:
                chord_cn, chord_en = chord_patterns[interval_pattern]
                
                root_note = self.note_info_cache[list(self.active_notes.keys())[0]]['note_letter']
                
                return f"{root_note}{chord_en} ({chord_cn})"
        
        chord_by_letters = self.detect_chord_by_letters(unique_letters)
        if chord_by_letters:
            return chord_by_letters
            
        return f"未知和弦 ({', '.join(unique_letters)})"

    def detect_chord_by_letters(self, note_letters):
        chord_letter_patterns = {
            frozenset({'C', 'E', 'G'}): 'C大三和弦',
            frozenset({'C', 'Eb', 'G'}): 'C小三和弦',
            frozenset({'C', 'Eb', 'Gb'}): 'C减三和弦',
            frozenset({'C', 'E', 'G#'}): 'C增三和弦',
            
            frozenset({'G', 'B', 'D'}): 'G大三和弦',
            frozenset({'G', 'Bb', 'D'}): 'G小三和弦',
            frozenset({'G', 'Bb', 'Db'}): 'G减三和弦',
            frozenset({'G', 'B', 'D#'}): 'G增三和弦',
            
            frozenset({'D', 'F#', 'A'}): 'D大三和弦',
            frozenset({'D', 'F', 'A'}): 'D小三和弦',
            frozenset({'D', 'F', 'Ab'}): 'D减三和弦',
            frozenset({'D', 'F#', 'A#'}): 'D增三和弦',
        }
        
        letter_set = frozenset(note_letters)
        return chord_letter_patterns.get(letter_set, "")

    def all_notes_off(self):
        """发送所有音符关闭到所有端口"""
        for port in self.output_ports:
            if port:
                try:
                    for channel in range(16):
                        port.send(mido.Message('control_change', channel=channel, control=123, value=0))
                        time.sleep(0.0005)
                except Exception as e:
                    self.log_message(f"端口{port.name}发送音符关闭消息失败: {str(e)}", "ERROR")
        
        self.log_message("已发送所有音符关闭消息到所有端口", "INFO")

    def format_time(self, seconds):
        minutes = int(seconds // 60)
        secs = int(seconds % 60)
        return f"{minutes:02d}:{secs:02d}"

    def log_message(self, message, level="INFO"):
        if self.log_levels.get(level, False):
            current_time = time.localtime()
            ms = int((time.time() % 1) * 1000)
            timestamp = f"{current_time.tm_hour:02d}:{current_time.tm_min:02d}:{current_time.tm_sec:02d}.{ms:03d}"
            self.update_log.emit(level, f"[{timestamp}] [{level}] {message}")

    def update_log_levels(self):
        self.log_levels['DEBUG'] = self.debug_check.isChecked()
        self.log_levels['INFO'] = self.info_check.isChecked()
        self.log_levels['WARN'] = self.warn_check.isChecked()
        self.log_levels['ERROR'] = self.error_check.isChecked()

    def update_performance_data(self):
        """高频更新性能监控数据"""
        if not self.is_playing:
            return
            
        current_time = time.time()
        elapsed = current_time - self.last_perf_update
        
        if elapsed >= 0.005:
            # 计算吞吐量
            new_messages = self.message_count - self.last_message_count
            throughput = new_messages / elapsed if elapsed > 0 else 0
            
            # 计算平均延迟
            avg_latency = self.total_latency / self.latency_count if self.latency_count > 0 else 0
            
            # 队列状态
            queue_size = self.midi_event_queue.qsize()
            queue_percent = (queue_size / self.midi_event_queue.maxsize) * 100
            
            # 活跃端口数
            active_ports = len([port for port in self.output_ports if port is not None])
            
            # 更新性能标签
            self.update_performance.emit('message_count', float(self.message_count))
            self.update_performance.emit('throughput', throughput)
            self.update_performance.emit('latency', avg_latency)
            self.update_performance.emit('active_count', float(len(self.active_notes)))
            
            # 更新队列状态标签
            self.queue_label.setText(f"队列: {queue_size}/{self.midi_event_queue.maxsize} ({queue_percent:.0f}%)")
            
            # 更新端口计数标签
            self.port_label.setText(f"活跃端口: {active_ports}")
            
            # 更新统计数据
            self.last_message_count = self.message_count
            self.last_perf_update = current_time

    def update_progress_display(self):
        """独立的进度条更新，仅显示，不可交互"""
        if not self.is_playing or self.total_file_duration == 0:
            return
            
        # 计算当前播放时间
        if self.play_start_time:
            self.current_play_time = time.time() - self.play_start_time
            
        # 限制最大进度为100%
        if self.current_play_time > self.total_file_duration:
            self.current_play_time = self.total_file_duration
            
        # 更新进度条和时间显示
        progress = (self.current_play_time / self.total_file_duration) * 100
        progress = max(0, min(100, progress))
        
        current_str = self.format_time(self.current_play_time)
        total_str = self.format_time(self.total_file_duration)
        
        # 直接更新UI
        self.progress_bar.setValue(int(progress))
        self.progress_label.setText(f"{current_str} / {total_str}")

    def toggle_floating_harmony_window(self):
        """切换浮动复音窗口"""
        if self.floating_harmony_window is None or not self.floating_harmony_window.isVisible():
            # 创建新的浮动窗口
            self.floating_harmony_window = FloatingHarmonyWindow(self)
            self.floating_harmony_window.closed.connect(self.on_floating_window_closed)
            self.floating_harmony_window.show()
            
            # 隐藏主窗口中的表格
            self.harmony_table.setVisible(False)
            
            # 更新按钮图标
            self.float_btn.setIcon(QIcon.fromTheme("window-close"))
            self.float_btn.setToolTip("关闭浮动窗口")
        else:
            # 关闭浮动窗口
            self.floating_harmony_window.close()

    def on_floating_window_closed(self):
        """浮动窗口关闭事件"""
        self.floating_harmony_window = None
        
        # 显示主窗口中的表格
        self.harmony_table.setVisible(True)
        
        # 恢复按钮图标
        self.float_btn.setIcon(QIcon.fromTheme("window-new"))
        self.float_btn.setToolTip("浮动窗口")

    def process_ui_queue(self):
        try:
            while not self.ui_queue.empty():
                pass
        except:
            pass

    @pyqtSlot(str, QColor)
    def on_update_status(self, text, color):
        self.status_label.setText(text)
        self.status_label.setStyleSheet(f"font-size: 11pt; font-weight: bold; color: {color.name()};")

    @pyqtSlot(list)
    def on_update_harmony_table(self, data):
        # 更新主窗口表格
        if self.harmony_table.isVisible():
            self.harmony_table.setRowCount(0)
            for row_idx, row_data in enumerate(data):
                self.harmony_table.insertRow(row_idx)
                for col_idx, (key, value) in enumerate(row_data.items()):
                    item = QTableWidgetItem(value)
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.harmony_table.setItem(row_idx, col_idx, item)

    @pyqtSlot()
    def on_clear_harmony_table(self):
        if self.harmony_table.isVisible():
            self.harmony_table.setRowCount(0)

    @pyqtSlot(str)
    def on_update_theory_text(self, text):
        self.theory_text.setText(text)

    @pyqtSlot(list)
    def on_update_history_list(self, items):
        self.history_list.clear()
        self.history_list.addItems(items)

    @pyqtSlot(int, str)
    def on_update_progress(self, progress, text):
        # 这个信号现在很少使用，主要由update_progress_display直接更新
        self.progress_bar.setValue(progress)
        self.progress_label.setText(text)

    @pyqtSlot(str, float)
    def on_update_performance(self, type_name, value):
        if type_name == 'message_count':
            self.msg_count_label.setText(f"消息计数: {int(value)}")
        elif type_name == 'throughput':
            self.throughput_label.setText(f"吞吐量: {value:.1f} msg/s")
        elif type_name == 'latency':
            self.latency_label.setText(f"平均延迟: {value:.2f} ms")
        elif type_name == 'active_count':
            self.active_count_label.setText(f"活跃音符: {int(value)}")

    @pyqtSlot(str, str)
    def on_update_log(self, level, message):
        color_map = {
            'DEBUG': '#808080',
            'INFO': '#000000',
            'WARN': '#FF8C00',
            'ERROR': '#FF0000',
            'SUCCESS': '#008000'
        }
        
        color = color_map.get(level, '#000000')
        self.log_text.setTextColor(QColor(color))
        self.log_text.append(message)
        self.log_text.moveCursor(QTextCursor.MoveOperation.End)

    def closeEvent(self, event):
        self.log_message("正在关闭midi虚拟接口输出", "INFO")
        
        self.quit_event.set()
        self.stop_play()
        
        # 停止定时器
        self.ui_timer.stop()
        self.perf_timer.stop()
        self.progress_timer.stop()
        
        # 关闭浮动窗口
        if self.floating_harmony_window:
            self.floating_harmony_window.close()
            
        # 等待线程结束
        for name, thread in self.threads.items():
            if thread.is_alive():
                thread.join(timeout=0.5)
                
        # 关闭所有端口
        for i, port in enumerate(self.output_ports):
            if port:
                try:
                    port.close()
                    self.log_message(f"已关闭端口{i + 1}: {port.name}", "INFO")
                except:
                    pass
            
        self.log_message("midi虚拟接口输出已关闭", "INFO")
        event.accept()

def main():
    app = QApplication(sys.argv)
    
    # 设置应用程序图标主题（如果可用）
    app.setStyle("Fusion")
    
    player = MIDIVirtualPlayer()
    player.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()