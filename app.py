import tkinter as tk
from tkinter import font, messagebox
import json
import os
from datetime import datetime, timedelta
import threading
import subprocess
import winreg
import sys

# Проверяем наличие psutil, если нет - устанавливаем
try:
    import psutil
except ImportError:
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "psutil", "-q"])
        import psutil
    except:
        psutil = None
try:
    from pystray import Icon, Menu, MenuItem
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
    TRAY_AVAILABLE = True
except:
    PIL_AVAILABLE = False
    TRAY_AVAILABLE = False

class SingleInstanceChecker:
    """Проверка на множественное открытие приложения с файловым локом"""
    
    def __init__(self):
        self.lock_file_path = os.path.join(os.path.expanduser("~"), ".token_widget.lock")
        self.lock_file = None
        self.has_lock = False
    
    def is_instance_running(self):
        """Проверить, запущен ли уже экземпляр приложения"""
        try:
            # Если файл не существует, процесс не работает
            if not os.path.exists(self.lock_file_path):
                return False
            
            # Если файл существует, пытаемся открыть его для чтения
            try:
                with open(self.lock_file_path, 'r') as f:
                    pid_str = f.read().strip()
                    if pid_str and pid_str.isdigit():
                        pid = int(pid_str)
                        
                        # Если psutil доступен, используем его для точной проверки
                        if psutil:
                            if psutil.pid_exists(pid):
                                return True
                            else:
                                # PID не существует, удаляем старый файл
                                try:
                                    os.remove(self.lock_file_path)
                                except:
                                    pass
                                return False
                        else:
                            # psutil не доступен, предполагаем что процесс работает
                            return True
            except IOError:
                # Файл заблокирован - его держит другой процесс
                return True
            
            return False
        except:
            return False
    
    def acquire_lock(self):
        """Попытка захватить лок"""
        try:
            # Если файл существует, пытаемся его удалить
            if os.path.exists(self.lock_file_path):
                try:
                    os.remove(self.lock_file_path)
                except OSError:
                    # Если не удалось удалить - его держит другой процесс
                    return False
            
            # Создаём новый файл с текущим PID
            self.lock_file = open(self.lock_file_path, 'w')
            self.lock_file.write(str(os.getpid()))
            self.lock_file.flush()
            self.has_lock = True
            return True
        except Exception as e:
            print(f"Ошибка захвата лока: {e}")
            return False
    
    def release(self):
        """Освободить лок"""
        try:
            if self.lock_file:
                self.lock_file.close()
                self.lock_file = None
            
            # Пытаемся удалить файл несколько раз
            for attempt in range(3):
                try:
                    if os.path.exists(self.lock_file_path):
                        os.remove(self.lock_file_path)
                    break
                except Exception as e:
                    if attempt < 2:
                        import time
                        time.sleep(0.1)
                    else:
                        pass
            
            self.has_lock = False
        except:
            pass

class TokenWidget:
    MODEL_MULTIPLIERS = {
        "glm-4.6": 0.25,
        "claude-haiku-4-5-20251001": 0.4,
        "gpt-5.1": 0.5,
        "gpt-5.1-codex": 0.5,
        "gpt-5.1-codex-max": 0.5,
        "gpt-5.2": 0.7,
        "gemini-3-pro-preview": 0.8,
        "claude-sonnet-4-5-20250929": 1.2,
        "claude-opus-4-5-20251101": 2.0,
        "claude-opus-4-1-20250805": 6.0,
    }
    
    MONTHLY_LIMIT = 20_000_000
    THEME_LIGHT = "light"
    THEME_DARK = "dark"
    
    def __init__(self, root):
        self.root = root
        self.single_instance = SingleInstanceChecker()
        
        print("DEBUG: Начало инициализации")
        
        # Сначала проверяем, работает ли уже экземпляр
        if self.single_instance.is_instance_running():
            print("DEBUG: Обнаружен работающий экземпляр")
            # Приложение уже запущено
            self.root.withdraw()
            self.root.after(100, self.root.quit)
            return
        
        print("DEBUG: Экземпляр не найден, захватываем лок")
        
        # Пытаемся захватить лок
        if not self.single_instance.acquire_lock():
            print("DEBUG: Не удалось захватить лок")
            # Не смогли захватить лок - приложение уже работает
            self.root.withdraw()
            self.root.after(100, self.root.quit)
            return
        
        print("DEBUG: Лок захвачен успешно")
        
        self.root.protocol("WM_DESTROY", self.cleanup_on_exit)
        
        self.compact_mode = True
        self.config_file = os.path.join(os.path.expanduser("~"), ".token_widget.json")
        self.sessions_dir = os.path.join(os.path.expanduser("~"), ".factory", "sessions")
        self.load_data()
        
        print(f"DEBUG: Размер окна {self.miniature_mode}, компактный режим: {self.compact_mode}")
        
        self.root.title("Токены")
        
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        
        if self.miniature_mode:
            w, h = 50, 50
        else:
            w, h = 170, 150
        
        new_x = self.current_x
        new_y = self.current_y
        
        if new_x < 0 or new_x + w > screen_w:
            new_x = 10
        if new_y < 0 or new_y + h > screen_h:
            new_y = 10
        
        self.current_x = new_x
        self.current_y = new_y
        
        print(f"DEBUG: Геометрия окна: {w}x{h}+{new_x}+{new_y}")
        self.root.geometry(f"{w}x{h}+{new_x}+{new_y}")
        self.root.attributes("-alpha", self.alpha_value)
        self.root.overrideredirect(True)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        
        self.drag_data = {"x": 0, "y": 0}
        self.root.bind("<Button-1>", self.on_click)
        self.root.bind("<B1-Motion>", self.on_drag)
        self.root.bind("<Button-3>", self.show_menu)
        
        self.icon = None
        self.tray_thread = None
        
        print("DEBUG: Показываем окно")
        # Показываем окно по умолчанию
        self.root.deiconify()
        self.root.lift()
        print("DEBUG: Окно должно быть видно")
        
        self.bg_color = "#0d1117"
        self.fg_color = "#58a6ff"
        self.root.configure(bg=self.bg_color)
        
        self.main_frame = tk.Frame(self.root, bg=self.bg_color)
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        
        self.create_ui()
        self.update_display()
        self.schedule_refresh()
    
    def create_ui(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()
        
        if self.miniature_mode:
            self.create_miniature_ui()
        elif self.compact_mode:
            self.create_compact_ui()
        else:
            self.create_full_ui()
    
    def create_miniature_ui(self):
        info_font = font.Font(family="Segoe UI", size=12, weight="bold")
        
        self.percent_label = tk.Label(self.main_frame, text="0%", bg=self.bg_color, fg="#79c0ff", font=info_font, relief=tk.FLAT, bd=0)
        self.percent_label.pack()
    
    def create_compact_ui(self):
        self.main_frame.configure(relief=tk.FLAT, bd=0)
        
        info_font = font.Font(family="Segoe UI", size=15, weight="bold")
        small_font = font.Font(family="Segoe UI", size=10)
        tiny_font = font.Font(family="Segoe UI", size=8)
        
        self.total_label = tk.Label(self.main_frame, text="0", bg=self.bg_color, fg=self.fg_color, font=info_font, relief=tk.FLAT, bd=0)
        self.total_label.pack()
        
        self.model_label = tk.Label(self.main_frame, text="Haiku", bg=self.bg_color, fg="#79c0ff", font=small_font, relief=tk.FLAT, bd=0)
        self.model_label.pack()
        
        # Прогресс бар
        self.progress_frame = tk.Frame(self.main_frame, bg="#30363d", height=6)
        self.progress_frame.pack(fill=tk.X, pady=4)
        
        self.progress_bar = tk.Frame(self.progress_frame, bg="#238636", height=6)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.Y)
        
        self.percent_label = tk.Label(self.main_frame, text="0%", bg=self.bg_color, fg="#79c0ff", font=tiny_font, relief=tk.FLAT, bd=0)
        self.percent_label.pack()
    
    def create_full_ui(self):
        total_font = font.Font(family="Segoe UI", size=28, weight="bold")
        self.total_label = tk.Label(self.main_frame, text="0", bg=self.bg_color, fg=self.fg_color, font=total_font)
        self.total_label.pack(pady=(0, 2))
        
        sub_font = font.Font(family="Segoe UI", size=9)
        label = tk.Label(self.main_frame, text="Standard Tokens (эта сессия)", bg=self.bg_color, fg="#8b949e", font=sub_font)
        label.pack()
        
        self.model_label = tk.Label(self.main_frame, text="Модель: Не определена", bg=self.bg_color, fg="#79c0ff", font=sub_font)
        self.model_label.pack(pady=(6, 0))
        
        sep = tk.Frame(self.main_frame, bg="#30363d", height=1)
        sep.pack(fill=tk.X, pady=8)
        
        info_font = font.Font(family="Segoe UI", size=8)
        self.cache_label = tk.Label(self.main_frame, text="⚡ Кэш: 0 / 0 ST", bg=self.bg_color, fg="#79c0ff", font=info_font)
        self.cache_label.pack(anchor=tk.W)
        
        self.output_label = tk.Label(self.main_frame, text="📤 Выход: 0 / 0 ST", bg=self.bg_color, fg="#79c0ff", font=info_font)
        self.output_label.pack(anchor=tk.W, pady=1)
        
        self.input_label = tk.Label(self.main_frame, text="⬆️ Вход: 0 / 0 ST", bg=self.bg_color, fg="#79c0ff", font=info_font)
        self.input_label.pack(anchor=tk.W, pady=(1, 6))
        
        sep2 = tk.Frame(self.main_frame, bg="#30363d", height=1)
        sep2.pack(fill=tk.X, pady=4)
        
        self.overall_label = tk.Label(self.main_frame, text="Всего использовано", bg=self.bg_color, fg="#8b949e", font=info_font)
        self.overall_label.pack(anchor=tk.W)
        
        self.progress_frame = tk.Frame(self.main_frame, bg="#30363d", height=8)
        self.progress_frame.pack(fill=tk.X, pady=(2, 1))
        
        self.progress_bar = tk.Frame(self.progress_frame, bg="#238636", height=8)
        self.progress_bar.pack(side=tk.LEFT, fill=tk.Y)
        
        self.percent_label = tk.Label(self.main_frame, text="0% / 20M", bg=self.bg_color, fg="#79c0ff", font=info_font)
        self.percent_label.pack(anchor=tk.W, pady=(1, 4))
        
        self.cache_label2 = tk.Label(self.main_frame, text="Кэшированных токенов", bg=self.bg_color, fg="#8b949e", font=info_font)
        self.cache_label2.pack(anchor=tk.W)
        
        self.cache_progress_frame = tk.Frame(self.main_frame, bg="#30363d", height=6)
        self.cache_progress_frame.pack(fill=tk.X, pady=(2, 1))
        
        self.cache_progress_bar = tk.Frame(self.cache_progress_frame, bg="#79c0ff", height=6)
        self.cache_progress_bar.pack(side=tk.LEFT, fill=tk.Y)
        
        self.cache_percent_label = tk.Label(self.main_frame, text="0% кэша", bg=self.bg_color, fg="#79c0ff", font=info_font)
        self.cache_percent_label.pack(anchor=tk.W)
        
        sep3 = tk.Frame(self.main_frame, bg="#30363d", height=1)
        sep3.pack(fill=tk.X, pady=8)
        
        settings_label = tk.Label(self.main_frame, text="Настройки", bg=self.bg_color, fg="#8b949e", font=info_font)
        settings_label.pack(anchor=tk.W)
        
        mode_frame = tk.Frame(self.main_frame, bg=self.bg_color)
        mode_frame.pack(anchor=tk.W, fill=tk.X, pady=4)
        tk.Label(mode_frame, text="Режим:", bg=self.bg_color, fg="#79c0ff", font=info_font).pack(side=tk.LEFT)
        tk.Button(mode_frame, text="Миниатюра (50×50)", command=self.toggle_miniature, bg="#58a6ff", fg="#ffffff", font=info_font, relief=tk.FLAT).pack(side=tk.LEFT, padx=5)
        
        alpha_label = tk.Label(self.main_frame, text="Прозрачность:", bg=self.bg_color, fg="#79c0ff", font=info_font)
        alpha_label.pack(anchor=tk.W)
        
        self.alpha_scale = tk.Scale(self.main_frame, from_=0.3, to=1.0, resolution=0.05, orient=tk.HORIZONTAL, bg="#1c2128", fg="#79c0ff", length=350, command=self.change_alpha, highlightthickness=0, bd=0)
        self.alpha_scale.set(self.alpha_value)
        self.alpha_scale.pack(anchor=tk.W, fill=tk.X, padx=2)
        
        btn_frame = tk.Frame(self.main_frame, bg=self.bg_color)
        btn_frame.pack(pady=8, fill=tk.X)
        
        btn_font = font.Font(family="Segoe UI", size=8)
        tk.Button(btn_frame, text="↻", command=self.refresh_sessions, bg="#238636", fg="#ffffff", font=btn_font, width=4, relief=tk.FLAT).pack(side=tk.LEFT, padx=1)
        tk.Button(btn_frame, text="✕", command=self.reset, bg="#da3633", fg="#ffffff", font=btn_font, width=4, relief=tk.FLAT).pack(side=tk.LEFT, padx=1)
        tk.Button(btn_frame, text="⚙", command=self.reset_position, bg="#0969da", fg="#ffffff", font=btn_font, width=4, relief=tk.FLAT).pack(side=tk.LEFT, padx=1)
        tk.Button(btn_frame, text="📋", command=self.copy_to_clipboard, bg="#1f6feb", fg="#ffffff", font=btn_font, width=4, relief=tk.FLAT).pack(side=tk.LEFT, padx=1)
        tk.Button(btn_frame, text="🔔", command=lambda: self.toggle_notify(), bg="#6e40aa", fg="#ffffff", font=btn_font, width=4, relief=tk.FLAT).pack(side=tk.LEFT, padx=1)
        tk.Button(btn_frame, text="🚀", command=self.toggle_autostart, bg="#f85149", fg="#ffffff", font=btn_font, width=4, relief=tk.FLAT).pack(side=tk.LEFT, padx=1)
    
    def load_data(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file) as f:
                    data = json.load(f)
                    self.total_session = data.get("total", 0)
                    self.alpha_value = data.get("alpha", 0.95)
                    self.current_x = data.get("pos_x", 50)
                    self.current_y = data.get("pos_y", 50)
                    self.theme = data.get("theme", self.THEME_DARK)
                    self.miniature_mode = data.get("miniature", False)
                    self.notify_enabled = data.get("notify", True)
            except:
                self.total_session = 0
                self.alpha_value = 0.95
                self.current_x = 50
                self.current_y = 50
                self.theme = self.THEME_DARK
                self.miniature_mode = False
                self.notify_enabled = True
        else:
            self.total_session = 0
            self.alpha_value = 0.95
            self.current_x = 50
            self.current_y = 50
            self.theme = self.THEME_DARK
            self.miniature_mode = False
            self.notify_enabled = True
        
        # Если total == 0, загружаем историю из файла истории (восстановление при первом запуске)
        if self.total_session == 0:
            self.total_session = self.load_history_total()
        
        self.current_model = None
        self.multiplier = 1.0
        self.input_raw = 0
        self.output_raw = 0
        self.cache_create_raw = 0
        self.cache_read_raw = 0
        self.input_st = 0
        self.output_st = 0
        self.cache_create_st = 0
        self.cache_read_st = 0
        
        # Отслеживание предыдущих значений для обнаружения новых токенов
        self.prev_input_st = 0
        self.prev_output_st = 0
        self.prev_cache_create_st = 0
        self.prev_cache_read_st = 0
        self.last_session_id = None
    
    def load_history_total(self):
        """Загружает общее количество токенов из файла истории"""
        history_file = os.path.join(os.path.expanduser("~"), ".token_history.json")
        total = 0
        
        try:
            if os.path.exists(history_file):
                with open(history_file, "r") as f:
                    history = json.load(f)
                    # Суммируем все токены из истории по всем датам
                    for date, data in history.items():
                        total += data.get("tokens", 0)
        except:
            pass
        
        return total
    
    def save_data(self):
        with open(self.config_file, "w") as f:
            json.dump({
                "total": self.total_session, 
                "alpha": self.alpha_value,
                "pos_x": self.current_x,
                "pos_y": self.current_y,
                "theme": self.theme,
                "miniature": self.miniature_mode,
                "notify": self.notify_enabled
            }, f)
    
    def save_history(self):
        history_file = os.path.join(os.path.expanduser("~"), ".token_history.json")
        today = datetime.now().strftime("%Y-%m-%d")
        
        try:
            if os.path.exists(history_file):
                with open(history_file, "r") as f:
                    history = json.load(f)
            else:
                history = {}
            
            total_st = self.input_st + self.output_st + self.cache_create_st + self.cache_read_st
            
            if today not in history:
                history[today] = {"sessions": 0, "tokens": 0}
            
            history[today]["tokens"] += total_st
            history[today]["sessions"] += 1
            
            with open(history_file, "w") as f:
                json.dump(history, f)
        except:
            pass
    
    def check_limit_warning(self):
        total_st = self.input_st + self.output_st + self.cache_create_st + self.cache_read_st
        percent = (total_st / self.MONTHLY_LIMIT) * 100
        
        if self.notify_enabled:
            if percent >= 90 and percent < 95:
                self.show_notification("⚠️ Внимание!", f"Использовано {percent:.1f}% лимита токенов!")
            elif percent >= 95:
                self.show_notification("🚨 Критично!", f"Использовано {percent:.1f}% лимита! Скоро закончатся токены!")
    
    def show_notification(self, title, message):
        try:
            if self.notify_enabled:
                messagebox.showwarning(title, message)
        except:
            pass
    
    def toggle_autostart(self):
        try:
            script_path = os.path.abspath(__file__)
            startup_folder = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
            
            bat_file = os.path.join(startup_folder, "token_tracker.bat")
            
            if os.path.exists(bat_file):
                os.remove(bat_file)
                messagebox.showinfo("Успех", "Автозапуск отключен")
                return False
            else:
                with open(bat_file, "w") as f:
                    f.write(f'@echo off\npython "{script_path}"\n')
                messagebox.showinfo("Успех", "Автозапуск включен")
                return True
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось изменить автозапуск: {e}")
    
    def is_autostart_enabled(self):
        startup_folder = os.path.join(os.path.expanduser("~"), "AppData", "Roaming", "Microsoft", "Windows", "Start Menu", "Programs", "Startup")
        bat_file = os.path.join(startup_folder, "token_tracker.bat")
        return os.path.exists(bat_file)
    
    def copy_to_clipboard(self):
        try:
            total_st = self.input_st + self.output_st + self.cache_create_st + self.cache_read_st
            percent = (total_st / self.MONTHLY_LIMIT) * 100
            
            text = f"Token Tracker: {total_st:,} ST ({percent:.2f}% лимита)"
            
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
            self.root.update()
            messagebox.showinfo("Успех", "Скопировано в буфер обмена")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось скопировать: {e}")
    
    def get_latest_session(self):
        try:
            if not os.path.exists(self.sessions_dir):
                return None
            
            latest_time = 0
            latest_file = None
            
            for root_dir in os.listdir(self.sessions_dir):
                full_path = os.path.join(self.sessions_dir, root_dir)
                if not os.path.isdir(full_path):
                    continue
                
                for file in os.listdir(full_path):
                    if file.endswith(".settings.json"):
                        file_path = os.path.join(full_path, file)
                        mod_time = os.path.getmtime(file_path)
                        if mod_time > latest_time:
                            latest_time = mod_time
                            latest_file = file_path
            
            return latest_file
        except:
            return None
    
    def refresh_sessions(self):
        try:
            session_file = self.get_latest_session()
            if not session_file:
                return
            
            # Получаем ID сессии чтобы обнаружить смену сессии
            session_id = os.path.basename(session_file)
            
            with open(session_file, "r") as f:
                data = json.load(f)
                
                model = data.get("model", "unknown")
                self.current_model = model
                self.multiplier = self.MODEL_MULTIPLIERS.get(model, 1.0)
                
                token_usage = data.get("tokenUsage", {})
                input_tokens = token_usage.get("inputTokens", 0)
                output_tokens = token_usage.get("outputTokens", 0)
                cache_create = token_usage.get("cacheCreationTokens", 0)
                cache_read = token_usage.get("cacheReadTokens", 0)
                
                self.input_raw = input_tokens
                self.output_raw = output_tokens
                self.cache_create_raw = cache_create
                self.cache_read_raw = cache_read
                
                new_input_st = int(input_tokens * self.multiplier)
                new_output_st = int(output_tokens * self.multiplier)
                new_cache_create_st = int(cache_create * self.multiplier / 10)
                new_cache_read_st = int(cache_read * self.multiplier / 10)
                
                # Если сессия изменилась, добавляем накопленные токены из старой сессии
                if session_id != self.last_session_id and self.last_session_id is not None:
                    accumulated = self.input_st + self.output_st + self.cache_create_st + self.cache_read_st
                    self.total_session += accumulated
                    self.save_data()
                
                # Если текущая сессия совпадает с предыдущей, проверяем увеличение токенов
                elif session_id == self.last_session_id:
                    # Проверяем, увеличились ли значения (это значит, что прошла новая запрос)
                    if new_input_st > self.input_st or new_output_st > self.output_st or \
                       new_cache_create_st > self.cache_create_st or new_cache_read_st > self.cache_read_st:
                        # Добавляем разницу к общему счетчику
                        delta_input = new_input_st - self.input_st
                        delta_output = new_output_st - self.output_st
                        delta_cache_create = new_cache_create_st - self.cache_create_st
                        delta_cache_read = new_cache_read_st - self.cache_read_st
                        
                        self.total_session += delta_input + delta_output + delta_cache_create + delta_cache_read
                        self.save_data()
                
                self.input_st = new_input_st
                self.output_st = new_output_st
                self.cache_create_st = new_cache_create_st
                self.cache_read_st = new_cache_read_st
                self.last_session_id = session_id
                
                self.update_display()
        except:
            pass
    
    def reset(self):
        self.total_session = 0
        self.save_data()
        self.update_display()
    
    def update_display(self):
        if self.current_model:
            parts = self.current_model.split("-")
            model_short = parts[-2] if len(parts) >= 2 else parts[0] if len(parts) > 0 else "?"
        else:
            model_short = "?"
        if self.current_model and "haiku" in self.current_model.lower():
            model_short = "Haiku"
        elif self.current_model and "sonnet" in self.current_model.lower():
            model_short = "Sonnet"
        elif self.current_model and "opus" in self.current_model.lower():
            model_short = "Opus"
        elif self.current_model and "gpt" in self.current_model.lower():
            model_short = "GPT"
        
        # total_session уже содержит накопленные токены из предыдущих сессий
        # current_session содержит токены из текущей активной сессии
        current_session = self.input_st + self.output_st + self.cache_create_st + self.cache_read_st
        total_st = self.total_session + current_session
        percent = (total_st / self.MONTHLY_LIMIT) * 100
        
        if not hasattr(self, 'total_label') and not hasattr(self, 'percent_label'):
            return
        
        # Обновляем total_label если есть
        if hasattr(self, 'total_label'):
            try:
                self.total_label.config(text=f"{total_st:,}")
            except:
                pass
        
        # Обновляем percent_label во всех режимах
        if hasattr(self, 'percent_label'):
            try:
                if self.miniature_mode:
                    # Микро режим: только процент
                    self.percent_label.config(text=f"{percent:.1f}%")
                elif self.compact_mode:
                    # Компактный режим: процент без "/ 20M"
                    self.percent_label.config(text=f"{percent:.1f}%")
                    
                    # Обновляем прогресс бар в компактном режиме
                    if hasattr(self, 'progress_bar'):
                        try:
                            progress_width = min(int((total_st / self.MONTHLY_LIMIT) * 150), 150)
                            self.progress_bar.config(width=progress_width)
                            
                            if percent > 80:
                                self.progress_bar.config(bg="#da3633")
                            elif percent > 50:
                                self.progress_bar.config(bg="#d29922")
                            else:
                                self.progress_bar.config(bg="#238636")
                        except:
                            pass
                else:
                    # Полный режим: процент с лимитом
                    self.percent_label.config(text=f"{percent:.2f}% / 20M")
            except:
                pass
        
        # Обновляем модель и другие элементы
        if hasattr(self, 'model_label'):
            try:
                self.model_label.config(text=f"{model_short}" if self.compact_mode else f"Модель: {model_short} (×{self.multiplier})")
            except:
                pass
        
        # Обновляем полный режим элементы
        if hasattr(self, 'cache_label') and not self.miniature_mode and not self.compact_mode:
            try:
                cache_total = self.cache_create_raw + self.cache_read_raw
                self.cache_label.config(text=f"⚡ Кэш: {cache_total:,} / {self.cache_create_st + self.cache_read_st:,} ST")
                self.output_label.config(text=f"📤 Выход: {self.output_raw:,} / {self.output_st:,} ST")
                self.input_label.config(text=f"⬆️ Вход: {self.input_raw:,} / {self.input_st:,} ST")
                
                progress_width = min(int((total_st / self.MONTHLY_LIMIT) * 356), 356)
                self.progress_bar.config(width=progress_width)
                
                if percent > 80:
                    self.progress_bar.config(bg="#da3633")
                elif percent > 50:
                    self.progress_bar.config(bg="#d29922")
                else:
                    self.progress_bar.config(bg="#238636")
            except:
                pass
            
            try:
                cache_st = self.cache_create_st + self.cache_read_st
                cache_percent = ((cache_st / total_st) * 100) if total_st > 0 else 0
                cache_width = min(int((cache_st / self.MONTHLY_LIMIT) * 356), 356)
                self.cache_progress_bar.config(width=cache_width)
                self.cache_percent_label.config(text=f"{cache_percent:.1f}% кэша ({cache_st:,} ST)")
            except:
                pass
    
    def schedule_refresh(self):
        self.refresh_sessions()
        self.save_history()
        self.check_limit_warning()
        self.root.after(2000, self.schedule_refresh)
    
    def setup_tray(self):
        if not TRAY_AVAILABLE:
            return
        
        def show_window(icon, item):
            self.root.after(0, lambda: (self.root.deiconify(), self.root.lift()))
        
        def hide_window_menu(icon, item):
            self.root.after(0, self.root.withdraw)
        
        def quit_app(icon, item):
            icon.stop()
            self.root.after(100, self.root.quit)
        
        try:
            # Создаём красивую иконку
            image = Image.new('RGB', (64, 64), color='#1c2128')
            draw = ImageDraw.Draw(image)
            # Рисуем голубой квадрат с буквой T
            draw.rectangle([4, 4, 60, 60], fill='#58a6ff', outline='#0d1117', width=2)
            draw.text((22, 18), 'T', fill='#0d1117')
        except:
            # Если не получилось, просто голубой квадрат
            image = Image.new('RGB', (64, 64), color='#58a6ff')
        
        menu = Menu(
            MenuItem('Показать', show_window),
            MenuItem('Скрыть', hide_window_menu),
            MenuItem('Выход', quit_app)
        )
        
        try:
            self.icon = Icon("token_tracker", image, menu=menu, default_menu_index=0)
            # Добавляем обработчик левого клика
            self.icon.left_click = show_window
            self.tray_thread = threading.Thread(target=self.icon.run, daemon=True)
            self.tray_thread.start()
        except Exception as e:
            print(f"Ошибка создания трея: {e}")
            raise
    
    def hide_window(self):
        self.root.withdraw()
    
    def on_click(self, event):
        self.drag_data["x"] = event.x_root - self.root.winfo_x()
        self.drag_data["y"] = event.y_root - self.root.winfo_y()
        self.root.after(300, self.check_double_click)
        self.last_click_time = self.root.tk.call('clock', 'clicks', '-milliseconds')
    
    def check_double_click(self):
        current_time = self.root.tk.call('clock', 'clicks', '-milliseconds')
        if hasattr(self, 'last_click_time') and (current_time - self.last_click_time) < 300:
            self.toggle_mode()
    
    def on_drag(self, event):
        x = event.x_root - self.drag_data["x"]
        y = event.y_root - self.drag_data["y"]
        
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        
        if self.miniature_mode:
            w, h = 50, 50
        elif self.compact_mode:
            w, h = 170, 150
        else:
            w, h = 420, 480
        
        if x < 0:
            x = 0
        if y < 0:
            y = 0
        if x + w > screen_w:
            x = max(0, screen_w - w)
        if y + h > screen_h:
            y = max(0, screen_h - h)
        
        self.root.geometry(f"+{x}+{y}")
        
        self.current_x = x
        self.current_y = y
        self.save_data()
    
    def toggle_mode(self, event=None):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        
        old_x = self.root.winfo_x()
        old_y = self.root.winfo_y()
        old_w = self.root.winfo_width()
        old_h = self.root.winfo_height()
        
        # Вычисляем якоря: прижато ли к краям?
        at_left = old_x < 10
        at_right = (old_x + old_w) > (screen_w - 10)
        at_top = old_y < 10
        at_bottom = (old_y + old_h) > (screen_h - 10)
        
        if self.miniature_mode:
            # Переход из микро в компактный
            self.miniature_mode = False
            self.compact_mode = True
            w, h = 170, 150
        elif self.compact_mode:
            # Переход из компактного в полный
            self.miniature_mode = False
            self.compact_mode = False
            w, h = 420, 480
        else:
            # Переход из полного в микро
            self.miniature_mode = True
            self.compact_mode = False
            w, h = 50, 50
        
        # Вычисляем новую позицию с учетом якорей
        if at_left:
            new_x = 0
        elif at_right:
            new_x = screen_w - w
        else:
            new_x = old_x
        
        if at_top:
            new_y = 0
        elif at_bottom:
            new_y = screen_h - h
        else:
            new_y = old_y
        
        # Страховка на случай если вычисления дали отрицательные значения
        new_x = max(0, min(new_x, screen_w - w))
        new_y = max(0, min(new_y, screen_h - h))
        
        self.current_x = new_x
        self.current_y = new_y
        self.root.geometry(f"{w}x{h}+{new_x}+{new_y}")
        
        self.save_data()
        self.create_ui()
        self.update_display()
    
    def show_menu(self, event=None):
        menu = tk.Menu(self.root, tearoff=0, bg="#1c2128", fg="#c9d1d9")
        menu.add_command(label="Развернуть/Свернуть", command=self.toggle_mode)
        menu.add_command(label="Обновить", command=self.refresh_sessions)
        menu.add_separator()
        menu.add_command(label="Выход", command=self.root.quit)
        menu.post(event.x_root, event.y_root)
    
    def change_alpha(self, value):
        alpha = float(value)
        self.alpha_value = alpha
        self.root.attributes("-alpha", alpha)
        self.save_data()
    
    def toggle_notify(self):
        self.notify_enabled = not self.notify_enabled
        self.save_data()
        status = "включены" if self.notify_enabled else "отключены"
        messagebox.showinfo("Уведомления", f"Уведомления {status}")
    
    def toggle_miniature(self):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        
        old_x = self.root.winfo_x()
        old_y = self.root.winfo_y()
        old_w = self.root.winfo_width()
        old_h = self.root.winfo_height()
        
        # Вычисляем якоря: прижато ли к краям?
        at_left = old_x < 10
        at_right = (old_x + old_w) > (screen_w - 10)
        at_top = old_y < 10
        at_bottom = (old_y + old_h) > (screen_h - 10)
        
        self.miniature_mode = not self.miniature_mode
        self.compact_mode = self.miniature_mode and False or not self.miniature_mode
        
        if self.miniature_mode:
            w, h = 50, 50
        else:
            w, h = 170, 150
        
        # Вычисляем новую позицию с учетом якорей
        if at_left:
            new_x = 0
        elif at_right:
            new_x = screen_w - w
        else:
            new_x = old_x
        
        if at_top:
            new_y = 0
        elif at_bottom:
            new_y = screen_h - h
        else:
            new_y = old_y
        
        # Страховка на случай если вычисления дали отрицательные значения
        new_x = max(0, min(new_x, screen_w - w))
        new_y = max(0, min(new_y, screen_h - h))
        
        self.current_x = new_x
        self.current_y = new_y
        self.root.geometry(f"{w}x{h}+{new_x}+{new_y}")
        self.save_data()
        self.create_ui()
        self.update_display()
    
    def reset_position(self):
        self.current_x = 50
        self.current_y = 50
        if self.compact_mode:
            self.root.geometry(f"170x150+{self.current_x}+{self.current_y}")
        else:
            self.root.geometry(f"420x480+{self.current_x}+{self.current_y}")
        self.save_data()
    
    def run(self):
        try:
            self.root.mainloop()
        finally:
            # Гарантируем очистку при выходе
            self.cleanup_on_exit()
    
    def cleanup_on_exit(self):
        """Очистка при выходе"""
        try:
            if self.icon:
                self.icon.stop()
        except:
            pass
        try:
            self.single_instance.release()
        except:
            pass

if __name__ == "__main__":
    try:
        root = tk.Tk()
        widget = TokenWidget(root)
        widget.run()
    except Exception as e:
        print(f"Ошибка: {e}")
        sys.exit(1)
