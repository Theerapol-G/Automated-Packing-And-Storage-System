import tkinter as tk
from tkinter import messagebox, ttk, colorchooser, filedialog
import yaml
import os
import logging
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from pathlib import Path
import json
from enum import Enum
from datetime import datetime
import cv2
from PIL import Image, ImageTk
import threading
import math
import serial
import serial.tools.list_ports

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('shape_app.log'),
        logging.StreamHandler()
    ]
)

class Theme(Enum):
    LIGHT = "light"
    DARK = "dark"
    BLUE = "blue"

@dataclass
class ThemeColors:
    bg: str
    fg: str
    button_bg: str
    button_fg: str
    canvas_bg: str
    canvas_fg: str
    accent: str

@dataclass
class ShapeData:
    shape: str
    color: str
    size: float = 1.0

class ShapeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("APS MARK II Human Machine Interface")
        self.root.geometry("800x480")
        
        # Initialize camera
        self.camera = None
        self.camera_thread = None
        self.is_camera_running = False
        
        # Initialize theme
        self.current_theme = Theme.DARK
        self.themes = {
            Theme.LIGHT: ThemeColors(
                bg="#f0f0f0",
                fg="#000000",
                button_bg="#e0e0e0",
                button_fg="#000000",
                canvas_bg="#ffffff",
                canvas_fg="#000000",
                accent="#007acc"
            ),
            Theme.DARK: ThemeColors(
                bg="#24252B",
                fg="#ffffff",
                button_bg="#3d3d3d",
                button_fg="#000000",
                canvas_bg="#1e1e1e",
                canvas_fg="#e0e0e0",
                accent="#007acc"
            ),
            Theme.BLUE: ThemeColors(
                bg="#e6f3ff",
                fg="#000000",
                button_bg="#cce8ff",
                button_fg="#000000",
                canvas_bg="#ffffff",
                canvas_fg="#000000",
                accent="#007acc"
            )
        }
        
        # Initialize variables
        self.current_page = tk.StringVar(value="shape_selector")
        self.selected_config = None
        self.required_quantity = 0
        self.current_quantity = 0
        self.is_processing = False
        
        # Initialize undo/redo stacks
        self.undo_stack: List[List[ShapeData]] = []
        self.redo_stack: List[List[ShapeData]] = []
        
        # Initialize variables with type hints
        self.shapes: List[ShapeData] = []
        self.shape_index: int = 0
        self.boxes: List[tk.Canvas] = []
        self.saved_configs: Dict[str, Dict[str, str]] = {}
        self.untitled_counter: int = 1
        self.config_file: Path = Path("shapes.yaml")
        
        # Style configuration
        self.style = ttk.Style()
        self._setup_styles()
        
        # Add serial communication variables
        self.serial_port = None
        self.is_connected = False
        self.available_ports = []
        
        self._setup_ui()
        self._setup_shortcuts()
        self.load_saved_configs()
        
        logging.info("ShapeApp initialized successfully")

    def _setup_styles(self) -> None:
        """Set up ttk styles with current theme."""
        colors = self.themes[self.current_theme]
        
        # Configure styles with smaller fonts
        self.style.configure(
            'Modern.TButton',
            padding=5,
            font=('Verdana', 10),
            background=colors.button_bg,
            foreground=colors.button_fg
        )
        
        self.style.configure(
            'Title.TLabel',
            font=('Verdana', 20, 'bold'),
            background=colors.bg,
            foreground=colors.fg
        )
        
        self.style.configure(
            'Subtitle.TLabel',
            font=('Verdana', 16, 'bold'),
            background=colors.bg,
            foreground=colors.fg
        )
        
        self.style.configure(
            'TFrame',
            background=colors.bg
        )
        
        self.style.configure(
            'TLabelframe',
            background=colors.bg,
            foreground=colors.fg
        )
        
        self.style.configure(
            'TLabelframe.Label',
            background=colors.bg,
            foreground=colors.fg
        )

    def _setup_shortcuts(self) -> None:
        """Set up keyboard shortcuts."""
        self.root.bind('<Control-z>', lambda e: self.undo())
        self.root.bind('<Control-y>', lambda e: self.redo())
        self.root.bind('<Control-s>', lambda e: self.save_shapes())
        self.root.bind('<Control-o>', lambda e: self.load_config())
        self.root.bind('<Delete>', lambda e: self.clear_shapes())
        self.root.bind('<Control-1>', lambda e: self.draw_circle())
        self.root.bind('<Control-2>', lambda e: self.draw_square())
        self.root.bind('<Control-3>', lambda e: self.draw_hexagon())
        self.root.bind('<Control-t>', lambda e: self.toggle_theme())

    def toggle_theme(self) -> None:
        """Toggle between available themes."""
        themes = list(Theme)
        current_index = themes.index(self.current_theme)
        next_index = (current_index + 1) % len(themes)
        self.current_theme = themes[next_index]
        self._setup_styles()
        self._apply_theme()
        logging.info(f"Theme changed to {self.current_theme.value}")

    def _apply_theme(self) -> None:
        """Apply current theme to all widgets."""
        colors = self.themes[self.current_theme]
        
        # Update root window
        self.root.configure(bg=colors.bg)
        
        # Update all canvases
        for canvas in self.boxes + self.preview_boxes:
            canvas.configure(bg=colors.canvas_bg, fg=colors.canvas_fg)
        
        # Update all frames
        for widget in self.root.winfo_children():
            if isinstance(widget, ttk.Frame):
                widget.configure(style='TFrame')
            elif isinstance(widget, ttk.LabelFrame):
                widget.configure(style='TLabelframe')

    def _setup_ui(self) -> None:
        """Set up the user interface with modern styling."""
        try:
            # Main container with padding
            main_container = ttk.Frame(self.root, padding="10")
            main_container.pack(fill=tk.BOTH, expand=True)

            # Header section
            header_frame = ttk.Frame(main_container)
            header_frame.pack(fill=tk.X, pady=(0, 5))

            # Configure grid columns with weights
            header_frame.grid_columnconfigure(0, weight=1)  # Left column
            header_frame.grid_columnconfigure(1, weight=2)  # Center column (wider)
            header_frame.grid_columnconfigure(2, weight=1)  # Right column

            # Left side - APS MARK II title
            title_label = ttk.Label(
                header_frame,
                text="APS MARK II",
                style='Title.TLabel'
            )
            title_label.grid(row=0, column=0, padx=5, sticky='w')

            # Center - Operator Settings title
            operator_title = ttk.Label(
                header_frame,
                text="Operator Settings",
                style='Subtitle.TLabel'
            )
            operator_title.grid(row=0, column=1, padx=10, sticky='nsew')

            # Create notebook for tabs
            self.notebook = ttk.Notebook(main_container)
            self.notebook.pack(fill=tk.BOTH, expand=True)

            # Create pages
            self._create_shape_selector_page()
            self._create_process_monitor_page()

            # Add pages to notebook
            self.notebook.add(self.shape_selector_container, text="Shape Configuration")
            self.notebook.add(self.process_monitor_container, text="Process Monitor")

            # Bind tab change event
            self.notebook.bind('<<NotebookTabChanged>>', self._on_tab_change)

            logging.info("UI setup completed successfully")
        except Exception as e:
            logging.error(f"Error setting up UI: {e}")
            messagebox.showerror("Error", "Failed to initialize the application interface")

    def _on_tab_change(self, event) -> None:
        """Handle tab change event."""
        try:
            current_tab = self.notebook.select()
            tab_text = self.notebook.tab(current_tab, "text")
            
            if tab_text == "Process Monitor":
                self._update_process_monitor()
            else:
                self._stop_camera()
                
            logging.info(f"Switched to tab: {tab_text}")
        except Exception as e:
            logging.error(f"Error handling tab change: {e}")

    def _update_process_monitor(self) -> None:
        """Update the Process Monitor display."""
        try:
            # Update status text with configuration details
            self.status_text.config(state=tk.NORMAL)
            self.status_text.delete(1.0, tk.END)
            
            # Add title
            self.status_text.insert(tk.END, "System Status\n")
            self.status_text.insert(tk.END, "=" * 30 + "\n\n")
            
            # Display configuration details if available
            if self.selected_config:
                # File name
                self.status_text.insert(tk.END, "File Name:\n")
                self.status_text.insert(tk.END, f"• {self.selected_config}\n\n")
                
                # Pattern details
                self.status_text.insert(tk.END, "Pattern Placement:\n")
                pattern = self.saved_configs[self.selected_config]
                pattern_text = f"• {pattern['TL']} {pattern['TR']}\n"
                pattern_text += f"• {pattern['BL']} {pattern['BR']}"
                self.status_text.insert(tk.END, pattern_text + "\n\n")
                
                # Quantity information
                self.status_text.insert(tk.END, "Quantity Information:\n")
                self.status_text.insert(tk.END, f"• Required: {self.required_quantity}\n")
                self.status_text.insert(tk.END, f"• Current: {self.current_quantity}\n")
                self.status_text.insert(tk.END, f"• Remaining: {self.required_quantity - self.current_quantity}\n\n")
                
                # Update pattern preview boxes
                self._update_pattern_preview_boxes(pattern)
            else:
                self.status_text.insert(tk.END, "No configuration loaded.\n")
                self.status_text.insert(tk.END, "Please select and apply a configuration from page 1.\n\n")
            
            # System status
            self.status_text.insert(tk.END, "System Status:\n")
            self.status_text.insert(tk.END, f"• Camera: {'Running' if self.is_camera_running else 'Stopped'}\n")
            self.status_text.insert(tk.END, f"• Processing: {'Active' if self.is_processing else 'Inactive'}\n")
            
            # Add progress bar text
            if self.required_quantity > 0:
                progress = (self.current_quantity / self.required_quantity) * 100
                self.status_text.insert(tk.END, f"• Progress: {progress:.1f}%\n")
            
            self.status_text.config(state=tk.DISABLED)
        except Exception as e:
            logging.error(f"Error updating process monitor: {e}")

    def _update_pattern_preview_boxes(self, config_data):
        """Update the pattern preview boxes with the shapes from the configuration."""
        try:
            # Update pattern preview boxes
            for i, key in enumerate(["TL", "TR", "BL", "BR"]):
                canvas = self.pattern_preview_boxes[i]
                canvas.delete("all")  # Clear canvas first
                shape_type = config_data[key]
                
                # Get canvas dimensions
                width = canvas.winfo_width() or 40
                height = canvas.winfo_height() or 40
                center_x = width // 2
                center_y = height // 2
                size = min(width, height) * 0.35
                
                if shape_type == "circle":
                    canvas.create_oval(
                        center_x - size, center_y - size,
                        center_x + size, center_y + size,
                        fill="grey", tags="shape"
                    )
                elif shape_type == "square":
                    canvas.create_rectangle(
                        center_x - size, center_y - size,
                        center_x + size, center_y + size,
                        fill="grey", tags="shape"
                    )
                elif shape_type == "hexagon":
                    points = self._calculate_hexagon_points(center_x, center_y, size)
                    canvas.create_polygon(points, fill="grey", tags="shape")
        except Exception as e:
            logging.error(f"Error updating pattern preview boxes: {e}")

    def _start_camera(self) -> None:
        """Start the camera feed."""
        try:
            if not self.is_camera_running:
                self.camera = cv2.VideoCapture(0)
                self.is_camera_running = True
                self.camera_thread = threading.Thread(target=self._update_camera_feed)
                self.camera_thread.daemon = True
                self.camera_thread.start()
                self._update_process_monitor()
        except Exception as e:
            logging.error(f"Error starting camera: {e}")
            messagebox.showerror("Error", "Failed to start camera")

    def _stop_camera(self) -> None:
        """Stop the camera feed."""
        try:
            self.is_camera_running = False
            if self.camera:
                self.camera.release()
                self.camera = None
            if self.camera_thread:
                self.camera_thread.join()
            self._update_process_monitor()
        except Exception as e:
            logging.error(f"Error stopping camera: {e}")
            messagebox.showerror("Error", "Failed to stop camera")

    def _update_camera_feed(self) -> None:
        """Update the camera feed display."""
        while self.is_camera_running:
            try:
                ret, frame = self.camera.read()
                if ret:
                    # Convert frame to PhotoImage
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    frame = cv2.resize(frame, (640, 480))
                    image = Image.fromarray(frame)
                    photo = ImageTk.PhotoImage(image=image)
                    
                    # Update canvas
                    self.camera_canvas.create_image(0, 0, image=photo, anchor=tk.NW)
                    self.camera_canvas.image = photo  # Keep a reference
            except Exception as e:
                logging.error(f"Error updating camera feed: {e}")
                break

    def _start_processing(self) -> None:
        """Start the shape processing and send command to Arduino."""
        try:
            if not self.selected_config:
                messagebox.showwarning("Warning", "No configuration selected!")
                return

            if not self.is_connected:
                messagebox.showwarning("Warning", "Serial connection is not established. Please connect first!")
                return

            # Get the shapes from the selected configuration
            config_data = self.saved_configs.get(self.selected_config, {})
            if not config_data:
                messagebox.showwarning("Warning", "Selected configuration is empty!")
                return
                
            # Get the required quantity (this should be set when configuration is applied)
            if not hasattr(self, 'required_quantity') or self.required_quantity <= 0:
                messagebox.showwarning("Warning", "Please set a valid quantity first!")
                return
                
            # Format the command string
            # Format: "Q:(quantity) P:(shape1) (shape2) (shape3) (shape4)"
            shapes_str = " ".join([config_data.get(key, "none") for key in ["TL", "TR", "BL", "BR"]])
            command = f"Q:{self.required_quantity} P:{shapes_str}"
            
            # Send the command to Arduino
            if self.serial_port and self.serial_port.is_open:
                try:
                    self.serial_port.write(command.encode())
                    self._update_response(f"Sent command: {command}\n")
                    
                    # Update processing state
                    self.is_processing = True
                    self._update_process_monitor()
                    
                    # Optional: Read response from Arduino
                    self._read_arduino_response()
                except Exception as e:
                    logging.error(f"Error sending command to Arduino: {e}")
                    messagebox.showerror("Error", f"Failed to send command: {str(e)}")
            else:
                messagebox.showwarning("Warning", "Serial port is not open!")
                
        except Exception as e:
            logging.error(f"Error starting processing: {e}")
            messagebox.showerror("Error", "Failed to start processing")

    def _stop_processing(self) -> None:
        """Stop the shape processing."""
        try:
            self.is_processing = False
            self._update_process_monitor()
        except Exception as e:
            logging.error(f"Error stopping processing: {e}")
            messagebox.showerror("Error", "Failed to stop processing")

    def init_placeholder(self, canvas):
        """Initialize a placeholder in the canvas."""
        # Adjust placeholder lines for smaller canvas
        canvas.create_line(10, 10, 80, 80, dash=(4, 2), fill="gray")
        canvas.create_line(80, 10, 10, 80, dash=(4, 2), fill="gray")
        canvas.create_text(45, 45, text="Select here", font=("Arial", 10, "bold"), fill="gray")

    def create_shape_button(self, parent: ttk.Frame, text: str, command: callable) -> None:
        """Create a modern-styled button for shape selection."""
        btn = ttk.Button(
            parent,
            text=text,
            style='Modern.TButton',
            command=command
        )
        btn.pack(pady=5, fill=tk.X)

    def draw_shape(self, shape: str, color: str) -> None:
        """Draw a shape on the current canvas with error handling."""
        try:
            if self.shape_index >= 4:
                messagebox.showwarning("Warning", "Maximum number of shapes reached!")
                return

            # Save current state for undo
            self.undo_stack.append(self.shapes.copy())
            self.redo_stack.clear()

            # Create new shape
            shape_data = ShapeData(shape=shape, color=color)
            self.shapes.append(shape_data)
            self.shape_index += 1

            # Update display
            self._update_display()
            logging.info(f"Shape {shape} drawn successfully")
        except Exception as e:
            logging.error(f"Error drawing shape: {e}")
            messagebox.showerror("Error", f"Failed to draw shape: {str(e)}")

    def draw_circle(self) -> None:
        """Draw a circle shape."""
        self.draw_shape("circle", "grey")

    def draw_square(self) -> None:
        """Draw a square shape."""
        self.draw_shape("square", "grey")

    def draw_hexagon(self) -> None:
        """Draw a hexagon shape."""
        self.draw_shape("hexagon", "grey")

    def _draw_preview_shape(self, canvas: tk.Canvas, shape_data: ShapeData) -> None:
        """Draw a shape in the preview canvas."""
        try:
            # Get canvas dimensions
            width = canvas.winfo_width() or 60  # Default to 60 if not yet rendered
            height = canvas.winfo_height() or 60  # Default to 60 if not yet rendered
            
            # Calculate center and size based on canvas dimensions
            center_x = width // 2
            center_y = height // 2
            size = min(width, height) * 0.35  # 35% of the smaller dimension

            if shape_data.shape == "circle":
                canvas.create_oval(
                    center_x - size, center_y - size,
                    center_x + size, center_y + size,
                    fill=shape_data.color
                )
            elif shape_data.shape == "square":
                canvas.create_rectangle(
                    center_x - size, center_y - size,
                    center_x + size, center_y + size,
                    fill=shape_data.color
                )
            elif shape_data.shape == "hexagon":
                points = self._calculate_hexagon_points(center_x, center_y, size)
                canvas.create_polygon(points, fill=shape_data.color)
        except Exception as e:
            logging.error(f"Error drawing preview shape: {e}")
            raise

    def _calculate_hexagon_points(self, center_x: float, center_y: float, size: float) -> List[Tuple[float, float]]:
        """Calculate points for a regular hexagon."""
        # Adjust size for hexagon to match visual size of circle and square
        size = size * 0.95  # Slightly reduce hexagon size for better visual balance
        points = []
        for i in range(6):
            angle = i * 60 - 30  # Start at -30 degrees to point hexagon up
            rad = math.radians(angle)
            x = center_x + size * math.cos(rad)
            y = center_y + size * math.sin(rad)
            points.append((x, y))
        return points

    def save_shapes(self) -> None:
        """Save the selected shapes to a YAML file with validation and error handling."""
        try:
            if len(self.shapes) < 4:
                messagebox.showwarning("Warning", "You must select 4 shapes before saving!")
                return

            # Create save dialog
            dialog = tk.Toplevel(self.root)
            dialog.title("Save Configuration")
            dialog.geometry("300x250")  
            dialog.transient(self.root)
            dialog.grab_set()

            # Center the dialog
            dialog.update_idletasks()
            width = dialog.winfo_width()
            height = dialog.winfo_height()
            x = (dialog.winfo_screenwidth() // 2) - (width // 2)
            y = (dialog.winfo_screenheight() // 2) - (height // 2)
            dialog.geometry(f'{width}x{height}+{x}+{y}')

            # Name entry
            name_frame = ttk.Frame(dialog, padding="5")
            name_frame.pack(fill=tk.X)

            ttk.Label(name_frame, text="Configuration Name:").pack(side=tk.LEFT)
            name_var = tk.StringVar()
            name_entry = ttk.Entry(name_frame, textvariable=name_var, width=20)
            name_entry.pack(side=tk.LEFT, padx=3)

            # Preview frame
            preview_frame = ttk.LabelFrame(dialog, text="Preview", padding="5")
            preview_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=3)

            # Create preview grid
            preview_boxes = []
            preview_frame_grid = ttk.Frame(preview_frame)
            preview_frame_grid.pack(expand=True)

            for i in range(2):
                for j in range(2):
                    canvas = tk.Canvas(
                        preview_frame_grid,
                        width=60,
                        height=60,
                        bg="white",
                        highlightthickness=1,
                        relief="solid"
                    )
                    canvas.grid(row=i, column=j, padx=1)
                    preview_boxes.append(canvas)

            # Function to update preview shapes
            def update_preview_shapes():
                for canvas in preview_boxes:
                    canvas.delete("all")
                
                for i, shape_data in enumerate(self.shapes):
                    if i < len(preview_boxes):
                        canvas = preview_boxes[i]
                        # Force canvas update to ensure proper dimensions
                        canvas.update_idletasks()
                        # Draw shape with consistent sizing
                        width = canvas.winfo_width() or 60
                        height = canvas.winfo_height() or 60
                        center_x = width // 2
                        center_y = height // 2
                        size = min(width, height) * 0.35

                        if shape_data.shape == "circle":
                            canvas.create_oval(
                                center_x - size, center_y - size,
                                center_x + size, center_y + size,
                                fill="grey"
                            )
                        elif shape_data.shape == "square":
                            canvas.create_rectangle(
                                center_x - size, center_y - size,
                                center_x + size, center_y + size,
                                fill="grey"
                            )
                        elif shape_data.shape == "hexagon":
                            points = self._calculate_hexagon_points(center_x, center_y, size)
                            canvas.create_polygon(points, fill="grey")

            # Update preview initially
            dialog.after(100, update_preview_shapes)  

            # Buttons frame
            button_frame = ttk.Frame(dialog, padding="5")
            button_frame.pack(fill=tk.X, pady=5)

            def confirm_save() -> None:
                try:
                    config_name = name_var.get().strip()
                    if not config_name:
                        messagebox.showwarning("Warning", "Configuration name cannot be empty!")
                        return

                    # Validate configuration name
                    if config_name in self.saved_configs:
                        if not messagebox.askyesno(
                            "Confirm Overwrite",
                            f"Configuration '{config_name}' already exists. Overwrite?"
                        ):
                            return

                    # Create configuration data
                    config_data = {
                        "TL": self.shapes[0].shape,
                        "TR": self.shapes[1].shape,
                        "BL": self.shapes[2].shape,
                        "BR": self.shapes[3].shape
                    }

                    # Save to file
                    self.saved_configs[config_name] = config_data
                    self._save_to_file()
                    self.update_config_dropdown()

                    # Show success message
                    messagebox.showinfo("Success", f"Configuration '{config_name}' saved successfully!")
                    dialog.destroy()

                    logging.info(f"Configuration '{config_name}' saved successfully")
                except Exception as e:
                    logging.error(f"Error saving configuration: {e}")
                    messagebox.showerror("Error", f"Failed to save configuration: {str(e)}")

            ttk.Button(
                button_frame,
                text="Cancel",
                style='Modern.TButton',
                command=dialog.destroy
            ).pack(side=tk.RIGHT, padx=3)

            ttk.Button(
                button_frame,
                text="Save",
                style='Modern.TButton',
                command=confirm_save
            ).pack(side=tk.RIGHT, padx=3)

            # Set focus to name entry
            name_entry.focus_set()

        except Exception as e:
            logging.error(f"Error in save_shapes: {e}")
            messagebox.showerror("Error", "Failed to create save dialog")

    def _save_to_file(self) -> None:
        """Save configurations to YAML file with error handling."""
        try:
            with open(self.config_file, "w") as f:
                yaml.dump(self.saved_configs, f, default_flow_style=False)
            logging.info("Configurations saved to file successfully")
        except Exception as e:
            logging.error(f"Error saving to file: {e}")
            raise

    def load_config(self) -> None:
        """Load the selected configuration with validation and error handling."""
        try:
            config_name = self.config_var.get()
            if not config_name:
                messagebox.showwarning("Warning", "No configuration selected!")
                return

            if config_name not in self.saved_configs:
                messagebox.showwarning("Warning", "Selected configuration not found!")
                return

            config_data = self.saved_configs[config_name]
            self._validate_config_data(config_data)
            self.update_preview(config_data)
            logging.info(f"Configuration '{config_name}' loaded successfully")
        except Exception as e:
            logging.error(f"Error loading configuration: {e}")
            messagebox.showerror("Error", f"Failed to load configuration: {str(e)}")

    def _validate_config_data(self, config_data: Dict[str, str]) -> bool:
        """Validate configuration data structure."""
        try:
            if not isinstance(config_data, dict):
                raise ValueError("Invalid data format")

            required_keys = {"TL", "TR", "BL", "BR"}
            if not all(key in config_data for key in required_keys):
                raise ValueError("Missing required shape positions")

            if not all(isinstance(value, str) for value in config_data.values()):
                raise ValueError("Invalid shape type format")

            if not all(value in {"circle", "square", "hexagon"} for value in config_data.values()):
                raise ValueError("Invalid shape type")

            return True
        except Exception as e:
            messagebox.showerror("Error", f"Invalid configuration data: {str(e)}")
            return False

    def clear_shapes(self):
        """Clear all shapes and reset the application state."""
        for canvas in self.boxes:
            canvas.delete("all")
        self.shapes.clear()
        self.shape_index = 0
        self.init_placeholder(self.boxes[0])  

    def load_saved_configs(self):
        """Load saved configurations from the YAML file."""
        if os.path.exists("shapes.yaml"):
            try:
                with open("shapes.yaml", "r") as f:
                    self.saved_configs = yaml.safe_load(f) or {}
                self.update_config_dropdown()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to load saved configurations: {e}")

    def update_config_dropdown(self):
        """Update the dropdown with saved configuration names."""
        self.config_dropdown["values"] = list(self.saved_configs.keys())

    def delete_config(self):
        """Delete the selected configuration."""
        config_name = self.config_var.get()
        if not config_name:
            messagebox.showwarning("Warning", "No configuration selected!")
            return

        if config_name in self.saved_configs:
            del self.saved_configs[config_name]
            self.update_config_dropdown()

            try:
                with open("shapes.yaml", "w") as f:
                    yaml.dump(self.saved_configs, f)
                messagebox.showinfo("Success", f"Configuration '{config_name}' deleted.")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to delete configuration: {e}")
        else:
            messagebox.showwarning("Warning", "Selected configuration not found!")

    def undo(self) -> None:
        """Undo the last shape operation."""
        if not self.undo_stack:
            return
            
        # Save current state to redo stack
        self.redo_stack.append(self.shapes.copy())
        
        # Restore previous state
        self.shapes = self.undo_stack.pop()
        self.shape_index = len(self.shapes)
        
        # Update display
        self._update_display()
        logging.info("Undo operation performed")

    def redo(self) -> None:
        """Redo the last undone operation."""
        if not self.redo_stack:
            return
            
        # Save current state to undo stack
        self.undo_stack.append(self.shapes.copy())
        
        # Restore next state
        self.shapes = self.redo_stack.pop()
        self.shape_index = len(self.shapes)
        
        # Update display
        self._update_display()
        logging.info("Redo operation performed")

    def _update_display(self) -> None:
        """Update the display with current shapes."""
        # Clear all boxes
        for canvas in self.boxes:
            canvas.delete("all")
        
        # Draw shapes
        for i, shape_data in enumerate(self.shapes):
            self._draw_shape(self.boxes[i], shape_data)
        
        # Initialize placeholder for next box
        if self.shape_index < 4:
            self.init_placeholder(self.boxes[self.shape_index])

    def _draw_shape(self, canvas: tk.Canvas, shape_data: ShapeData) -> None:
        """Draw a shape with custom properties."""
        try:
            # Get canvas dimensions
            width = canvas.winfo_width() or 90  
            height = canvas.winfo_height() or 90  
            
            # Calculate center and size based on canvas dimensions
            center_x = width // 2
            center_y = height // 2
            base_size = min(width, height) * 0.35  
            size = base_size * shape_data.size

            # Clear existing shapes
            canvas.delete("all")

            if shape_data.shape == "circle":
                canvas.create_oval(
                    center_x - size, center_y - size,
                    center_x + size, center_y + size,
                    fill=shape_data.color,
                    tags="shape"
                )
            elif shape_data.shape == "square":
                canvas.create_rectangle(
                    center_x - size, center_y - size,
                    center_x + size, center_y + size,
                    fill=shape_data.color,
                    tags="shape"
                )
            elif shape_data.shape == "hexagon":
                points = self._calculate_hexagon_points(center_x, center_y, size)
                canvas.create_polygon(points, fill=shape_data.color, tags="shape")
        except Exception as e:
            logging.error(f"Error drawing shape: {e}")
            raise

    def show_apply_dialog(self) -> None:
        """Show the apply dialog with configuration details and quantity input."""
        try:
            # Check if a configuration is loaded
            config_name = self.config_var.get()
            if not config_name:
                messagebox.showwarning("Warning", "Please select and load a configuration first!")
                return

            if config_name not in self.saved_configs:
                messagebox.showwarning("Warning", "Selected configuration not found!")
                return

            # Create apply dialog
            dialog = tk.Toplevel(self.root)
            dialog.title("Apply Configuration")
            dialog.geometry("400x420")  
            dialog.transient(self.root)
            dialog.grab_set()

            # Center the dialog
            dialog.update_idletasks()
            width = dialog.winfo_width()
            height = dialog.winfo_height()
            x = (dialog.winfo_screenwidth() // 2) - (width // 2)
            y = (dialog.winfo_screenheight() // 2) - (height // 2)
            dialog.geometry(f'{width}x{height}+{x}+{y}')

            # Configuration details frame
            details_frame = ttk.LabelFrame(dialog, text="Configuration Details", padding="10")
            details_frame.pack(fill=tk.X, padx=10, pady=5)

            # Show selected shapes
            shapes_frame = ttk.Frame(details_frame)
            shapes_frame.pack(fill=tk.X, pady=5)

            # Create preview grid
            preview_boxes = []
            for i in range(2):
                for j in range(2):
                    canvas = tk.Canvas(
                        shapes_frame,
                        width=100,
                        height=100,
                        bg="white",
                        highlightthickness=1,
                        relief="solid"
                    )
                    canvas.grid(row=i, column=j, padx=10, pady=10)
                    preview_boxes.append(canvas)

            # Get the loaded configuration data
            config_data = self.saved_configs[config_name]
            
            # Function to draw preview shapes
            def draw_preview_shapes():
                for i, key in enumerate(["TL", "TR", "BL", "BR"]):
                    canvas = preview_boxes[i]
                    canvas.delete("all")  
                    shape_type = config_data[key]
                    
                    # Get canvas dimensions
                    width = canvas.winfo_width() or 100  
                    height = canvas.winfo_height() or 100  
                    center_x = width // 2
                    center_y = height // 2
                    size = min(width, height) * 0.35  

                    if shape_type == "circle":
                        canvas.create_oval(
                            center_x - size, center_y - size,
                            center_x + size, center_y + size,
                            fill="grey", tags="shape"
                        )
                    elif shape_type == "square":
                        canvas.create_rectangle(
                            center_x - size, center_y - size,
                            center_x + size, center_y + size,
                            fill="grey", tags="shape"
                        )
                    elif shape_type == "hexagon":
                        points = self._calculate_hexagon_points(center_x, center_y, size)
                        canvas.create_polygon(points, fill="grey", tags="shape")

            # Draw shapes after a short delay to ensure canvases are ready
            dialog.after(100, draw_preview_shapes)

            # Quantity input frame
            quantity_frame = ttk.LabelFrame(dialog, text="Quantity", padding="10")
            quantity_frame.pack(fill=tk.X, padx=10, pady=5)

            ttk.Label(quantity_frame, text="Number of boxes:").pack(side=tk.LEFT)
            quantity_var = tk.StringVar(value="1")
            quantity_entry = ttk.Entry(quantity_frame, textvariable=quantity_var, width=10)
            quantity_entry.pack(side=tk.LEFT, padx=5)

            def confirm_apply() -> None:
                try:
                    quantity = int(quantity_var.get())
                    if quantity <= 0:
                        messagebox.showwarning("Warning", "Quantity must be greater than 0!")
                        return

                    # Set the selected configuration and quantity
                    self.selected_config = config_name
                    self.required_quantity = quantity
                    self.current_quantity = 0

                    # Update pattern preview boxes in Process Monitor page
                    for i, key in enumerate(["TL", "TR", "BL", "BR"]):
                        canvas = self.pattern_preview_boxes[i]
                        canvas.delete("all")  
                        shape_type = config_data[key]
                        
                        # Get canvas dimensions
                        width = canvas.winfo_width() or 40  
                        height = canvas.winfo_height() or 40  
                        center_x = width // 2
                        center_y = height // 2
                        size = min(width, height) * 0.35  

                        if shape_type == "circle":
                            canvas.create_oval(
                                center_x - size, center_y - size,
                                center_x + size, center_y + size,
                                fill="grey", tags="shape"
                            )
                        elif shape_type == "square":
                            canvas.create_rectangle(
                                center_x - size, center_y - size,
                                center_x + size, center_y + size,
                                fill="grey", tags="shape"
                            )
                        elif shape_type == "hexagon":
                            points = self._calculate_hexagon_points(center_x, center_y, size)
                            canvas.create_polygon(points, fill="grey", tags="shape")

                    # Show success message using messagebox
                    messagebox.showinfo("Success", f"Configuration '{config_name}' applied successfully!\nQuantity: {quantity}")
                    dialog.destroy()

                    # Update process monitor if it's visible
                    if self.notebook.select() == self.notebook.tabs()[1]:  
                        self._update_process_monitor()

                    logging.info(f"Configuration '{config_name}' applied with quantity: {quantity}")
                except ValueError:
                    messagebox.showwarning("Warning", "Please enter a valid number!")
                except Exception as e:
                    logging.error(f"Error applying configuration: {e}")
                    messagebox.showerror("Error", f"Failed to apply configuration: {str(e)}")

            # Buttons
            button_frame = ttk.Frame(dialog, padding="10")
            button_frame.pack(fill=tk.X)

            ttk.Button(
                button_frame,
                text="Cancel",
                command=dialog.destroy
            ).pack(side=tk.RIGHT, padx=5)

            ttk.Button(
                button_frame,
                text="Apply",
                command=confirm_apply
            ).pack(side=tk.RIGHT, padx=5)

            # Set focus to quantity entry
            quantity_entry.focus_set()

        except Exception as e:
            logging.error(f"Error in show_apply_dialog: {e}")
            messagebox.showerror("Error", f"Failed to create apply dialog: {str(e)}")

    def update_preview(self, config_data: Dict[str, str]) -> None:
        """Update the preview frame with the selected configuration."""
        try:
            # Clear preview boxes
            for canvas in self.preview_boxes:
                canvas.delete("all")

            # Draw preview shapes
            for i, key in enumerate(["TL", "TR", "BL", "BR"]):
                canvas = self.preview_boxes[i]
                shape_data = ShapeData(shape=config_data[key], color="grey")
                self._draw_preview_shape(canvas, shape_data)

            # Add hover effect
            for canvas in self.preview_boxes:
                canvas.bind("<Enter>", lambda e, c=canvas: self._preview_hover(c, True))
                canvas.bind("<Leave>", lambda e, c=canvas: self._preview_hover(c, False))

            logging.info("Preview updated successfully")
        except Exception as e:
            logging.error(f"Error updating preview: {e}")
            messagebox.showerror("Error", f"Failed to update preview: {str(e)}")

    def _preview_hover(self, canvas: tk.Canvas, enter: bool) -> None:
        """Handle preview box hover effect."""
        try:
            if enter:
                # Create highlight effect
                canvas.create_rectangle(
                    1, 1, canvas.winfo_width()-1, canvas.winfo_height()-1,  
                    outline=self.themes[self.current_theme].accent,
                    width=2
                )
            else:
                # Remove highlight effect
                for item in canvas.find_all():
                    if canvas.type(item) == "rectangle":
                        canvas.delete(item)
                # Redraw the shape if it exists
                for item in canvas.find_all():
                    if canvas.type(item) in ["oval", "polygon"]:
                        canvas.tag_raise(item)  
        except Exception as e:
            logging.error(f"Error in preview hover effect: {e}")

    def _refresh_ports(self) -> None:
        """Refresh the list of available COM ports."""
        try:
            self.available_ports = [port.device for port in serial.tools.list_ports.comports()]
            self.port_dropdown['values'] = self.available_ports
            
            if self.available_ports:
                if not self.port_var.get():
                    self.port_var.set(self.available_ports[0])
            else:
                self.port_var.set('')
                
        except Exception as e:
            logging.error(f"Error refreshing ports: {e}")
            messagebox.showerror("Error", "Failed to refresh COM ports")

    def _toggle_connection(self) -> None:
        """Toggle serial connection."""
        try:
            if not self.is_connected:
                port = self.port_var.get()
                if not port:
                    messagebox.showwarning("Warning", "Please select a COM port!")
                    return
                
                try:
                    self.serial_port = serial.Serial(port, 115200, timeout=1)
                    self.is_connected = True
                    self.connect_btn.configure(text="Disconnect")
                    self.port_dropdown.configure(state="disabled")
                    self._update_response("Connected to " + port + "\n")
                    
                    # Start continuous response checking
                    self._start_continuous_response_checking()
                    
                except serial.SerialException as e:
                    messagebox.showerror("Error", f"Failed to connect to {port}: {str(e)}")
                    return
            else:
                if self.serial_port:
                    self.serial_port.close()
                self.serial_port = None
                self.is_connected = False
                self.connect_btn.configure(text="Connect")
                self.port_dropdown.configure(state="readonly")
                self._update_response("Disconnected\n")
                
        except Exception as e:
            logging.error(f"Error toggling connection: {e}")
            messagebox.showerror("Error", "Failed to toggle connection")

    def _start_continuous_response_checking(self):
        """Start continuous checking for Arduino responses."""
        if self.is_connected:
            self._check_arduino_response()
            
    def _check_arduino_response(self):
        """Continuously check for Arduino responses."""
        try:
            if not self.is_connected:
                return
                
            # Check if there's data available to read
            if self.serial_port and self.serial_port.in_waiting > 0:
                # Read the response
                response = self.serial_port.readline().decode('utf-8', errors='replace').strip()
                if response:
                    self._update_response(f"Received: {response}\n")
                    
            # Schedule the next check regardless of whether data was found
            if self.is_connected:
                self.root.after(100, self._check_arduino_response)
                
        except Exception as e:
            logging.error(f"Error in continuous response checking: {e}")
            # Try to reconnect if there was an error
            if self.is_connected:
                self.root.after(1000, self._check_arduino_response)

    def _send_command(self) -> None:
        """Send command to Arduino."""
        try:
            if not self.is_connected:
                messagebox.showwarning("Warning", "Please connect to a COM port first!")
                return
                
            command = self.cmd_entry.get().strip()
            if not command:
                return
                
            try:
                self.serial_port.write(command.encode())
                self._update_response(f"Sent:{command}\n")
                
                # Clear the command entry
                self.cmd_entry.delete(0, tk.END)
                
                # Read response with timeout
                self._read_arduino_response()
                    
            except serial.SerialException as e:
                messagebox.showerror("Error", f"Failed to send command: {str(e)}")
                self._toggle_connection()  
                
        except Exception as e:
            logging.error(f"Error sending command: {e}")
            messagebox.showerror("Error", "Failed to send command")

    def _read_arduino_response(self) -> None:
        """Read response from Arduino with timeout."""
        try:
            if not self.is_connected:
                return
                
            # Wait a moment for Arduino to process and respond
            self.root.after(100, self._check_for_response)
        except Exception as e:
            logging.error(f"Error setting up response reading: {e}")
            
    def _check_for_response(self) -> None:
        """Check for response from Arduino."""
        try:
            if not self.is_connected:
                return
                
            # Check if there's data available to read
            if self.serial_port.in_waiting > 0:
                # Read the response
                response = self.serial_port.readline().decode('utf-8', errors='replace').strip()
                if response:
                    self._update_response(f"Received: {response}\n")
                    
                # Check if there's more data
                if self.serial_port.in_waiting > 0:
                    # Schedule another check
                    self.root.after(50, self._check_for_response)
        except Exception as e:
            logging.error(f"Error reading Arduino response: {e}")

    def _update_response(self, text: str) -> None:
        """Update the response text area."""
        try:
            self.response_text.config(state=tk.NORMAL)
            self.response_text.insert(tk.END, text)
            self.response_text.see(tk.END)
            self.response_text.config(state=tk.DISABLED)
        except Exception as e:
            logging.error(f"Error updating response: {e}")

    def _create_shape_selector_page(self) -> None:
        """Create the Shape Selector page."""
        try:
            # Main container with padding
            self.shape_selector_container = ttk.Frame(self.notebook)
            self.shape_selector_container.pack(fill=tk.BOTH, expand=True)

            # Left panel (shape grid) - Reduced padding
            left_panel = ttk.Frame(self.shape_selector_container)
            left_panel.pack(side=tk.LEFT, padx=10)

            # Shape grid frame
            grid_frame = ttk.Frame(left_panel)
            grid_frame.pack(pady=10)

            # Create a container frame for the grid to ensure proper centering
            grid_container = ttk.Frame(grid_frame)
            grid_container.pack(expand=True)

            # Create 2x2 grid of white boxes with reduced size and equal spacing
            for i in range(2):
                row_frame = ttk.Frame(grid_container)
                row_frame.pack(pady=1)
                for j in range(2):
                    canvas = tk.Canvas(
                        row_frame,
                        width=90,
                        height=90,
                        bg="white",
                        highlightthickness=1,
                        relief="solid"
                    )
                    canvas.pack(side=tk.LEFT, padx=1)
                    self.boxes.append(canvas)

            # Initialize first box
            self.init_placeholder(self.boxes[0])

            # Placement Configuration label with smaller font
            placement_label = ttk.Label(
                grid_frame,
                text="Placement Configuration",
                style='Subtitle.TLabel'
            )
            placement_label.pack(pady=(10, 5))

            # Save and Clear buttons below the grid
            button_frame = ttk.Frame(grid_frame)
            button_frame.pack(pady=5)

            ttk.Button(
                button_frame,
                text="Save",
                style='Modern.TButton',
                command=self.save_shapes
            ).pack(side=tk.LEFT, padx=3)

            ttk.Button(
                button_frame,
                text="Clear",
                style='Modern.TButton',
                command=self.clear_shapes
            ).pack(side=tk.LEFT, padx=3)

            # Shape selection panel with reduced width
            selection_panel = ttk.LabelFrame(self.shape_selector_container, text="Selectable Items", padding=5)
            selection_panel.pack(side=tk.LEFT, padx=10, fill=tk.Y)

            # Shape buttons with modern styling
            self.create_shape_button(selection_panel, "Circle", self.draw_circle)
            self.create_shape_button(selection_panel, "Square", self.draw_square)
            self.create_shape_button(selection_panel, "Hexagon", self.draw_hexagon)

            # Saved configurations panel with reduced width
            saved_panel = ttk.LabelFrame(self.shape_selector_container, text="Saved Configurations", padding=5)
            saved_panel.pack(side=tk.RIGHT, padx=10, fill=tk.Y)

            # Configuration dropdown with reduced width
            self.config_var = tk.StringVar()
            self.config_dropdown = ttk.Combobox(
                saved_panel,
                textvariable=self.config_var,
                state="readonly",
                width=20,
                height=100
            )
            self.config_dropdown.pack(pady=5)

            # Load and Delete buttons
            button_frame = ttk.Frame(saved_panel)
            button_frame.pack(pady=3)

            ttk.Button(
                button_frame,
                text="Load",
                style='Modern.TButton',
                command=self.load_config
            ).pack(side=tk.LEFT, padx=3)

            ttk.Button(
                button_frame,
                text="Delete",
                style='Modern.TButton',
                command=self.delete_config
            ).pack(side=tk.LEFT, padx=3)

            # Preview frame with reduced size
            preview_frame = ttk.LabelFrame(saved_panel, text="Preview", padding=3)
            preview_frame.pack(pady=5)

            # Create preview grid with smaller boxes
            self.preview_boxes = []
            for i in range(2):
                row_frame = ttk.Frame(preview_frame)
                row_frame.pack(pady=2)
                for j in range(2):
                    canvas = tk.Canvas(
                        row_frame,
                        width=60,
                        height=60,
                        bg="white",
                        highlightthickness=1
                    )
                    canvas.pack(side=tk.LEFT, padx=1)
                    self.preview_boxes.append(canvas)

            # Apply button
            apply_button_frame = ttk.Frame(saved_panel)
            apply_button_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=5)

            ttk.Button(
                apply_button_frame,
                text="Apply",
                style='Modern.TButton',
                command=self.show_apply_dialog
            ).pack(side=tk.RIGHT, padx=3)

        except Exception as e:
            logging.error(f"Error creating Shape Selector page: {e}")
            messagebox.showerror("Error", "Failed to create Shape Selector page")

    def _create_process_monitor_page(self) -> None:
        """Create the Process Monitor page with three frames."""
        try:
            # Main container for Process Monitor
            self.process_monitor_container = ttk.Frame(self.notebook)
            self.process_monitor_container.pack(fill=tk.BOTH, expand=True)

            # Left frame (Preview and Camera)
            left_frame = ttk.LabelFrame(self.process_monitor_container, text="Preview and Detection", padding="1 5 5 5")  
            left_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=3, pady=(0, 3))  

            # Top container for pattern and system info - moved up by 5 pixels
            top_container = ttk.Frame(left_frame)
            top_container.pack(fill=tk.X, expand=False, pady=(0, 3))  

            # Preview pattern frame - side by side with system info
            preview_frame = ttk.LabelFrame(top_container, text="Desired Pattern", padding="1 1 1 1")  
            preview_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=1)

            # Create a container frame for the preview grid
            preview_container = ttk.Frame(preview_frame)
            preview_container.pack(expand=True)

            # Create preview grid (4 white squares) with reduced size
            self.pattern_preview_boxes = []
            for i in range(2):
                row_frame = ttk.Frame(preview_container)
                row_frame.pack(pady=1)
                for j in range(2):
                    canvas = tk.Canvas(
                        row_frame,
                        width=40,
                        height=40,
                        bg="white",
                        highlightthickness=1,
                        relief="solid"
                    )
                    canvas.pack(side=tk.LEFT, padx=1)
                    self.pattern_preview_boxes.append(canvas)

            # System Information frame - Next to the desired pattern frame
            status_frame = ttk.LabelFrame(top_container, text="System Information", padding="3")
            status_frame.pack(side=tk.LEFT, fill=tk.BOTH, padx=3, expand=True)
            status_frame.configure(width=250)

            self.status_text = tk.Text(status_frame, height=8, width=25, font=('Arial', 8))
            self.status_text.pack(fill=tk.BOTH, expand=True)
            self.status_text.config(state=tk.DISABLED)

            # Camera feed frame - Below pattern and system info
            camera_frame = ttk.LabelFrame(left_frame, text="Live Camera Feed", padding="3")
            camera_frame.pack(fill=tk.BOTH, expand=True, pady=3)

            # Camera canvas with adjusted size
            self.camera_canvas = tk.Canvas(camera_frame, width=250, height=160)
            self.camera_canvas.pack(fill=tk.BOTH)

            
            # Right frame (Communication and Controls)
            right_frame = ttk.LabelFrame(self.process_monitor_container, text="System Controls", padding="5")
            right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=False, padx=3)
            right_frame.configure(width=250)  

            # Communication frame - Moved up
            comm_frame = ttk.LabelFrame(right_frame, text="Communication", padding="3")
            comm_frame.pack(fill=tk.BOTH, expand=True, pady=3)

            # Port selection frame
            port_frame = ttk.Frame(comm_frame)
            port_frame.pack(fill=tk.X, pady=2)

            ttk.Label(port_frame, text="Port:").pack(side=tk.LEFT, padx=2)
            
            # COM port dropdown
            self.port_var = tk.StringVar()
            self.port_dropdown = ttk.Combobox(
                port_frame,
                textvariable=self.port_var,
                state="readonly",
                width=10
            )
            self.port_dropdown.pack(side=tk.LEFT, padx=2)

            # Refresh and Connect buttons
            btn_frame = ttk.Frame(port_frame)
            btn_frame.pack(side=tk.LEFT, padx=2)

            ttk.Button(
                btn_frame,
                text="⟳",
                width=3,
                command=self._refresh_ports
            ).pack(side=tk.LEFT, padx=1)

            self.connect_btn = ttk.Button(
                btn_frame,
                text="Connect",
                width=8,
                command=self._toggle_connection
            )
            self.connect_btn.pack(side=tk.LEFT, padx=1)

            # Command entry frame
            cmd_frame = ttk.Frame(comm_frame)
            cmd_frame.pack(fill=tk.X, pady=5)

            ttk.Label(cmd_frame, text="Command:").pack(side=tk.LEFT, padx=2)
            
            self.cmd_entry = ttk.Entry(cmd_frame, width=20)
            self.cmd_entry.pack(side=tk.LEFT, padx=2, fill=tk.X, expand=True)

            ttk.Button(
                cmd_frame,
                text="Send",
                command=self._send_command
            ).pack(side=tk.LEFT, padx=2)

            # Response text area
            self.response_text = tk.Text(comm_frame, height=6, width=25, font=('Arial', 8))
            self.response_text.pack(fill=tk.BOTH, expand=True, pady=2)
            self.response_text.config(state=tk.DISABLED)

            # New Control frame with reset and start buttons
            control_frame = ttk.LabelFrame(right_frame, text="Control Panel", padding="3")
            control_frame.pack(fill=tk.BOTH, expand=True, pady=3)

            # Use a more direct approach to position buttons at bottom right
            # Fill the control frame with an empty expandable frame first
            filler_frame = ttk.Frame(control_frame)
            filler_frame.pack(fill=tk.BOTH, expand=True)
            
            # Button container at the bottom
            button_container = ttk.Frame(control_frame)
            button_container.pack(side=tk.BOTTOM, fill=tk.X, pady=10)

            # Reset button
            reset_button = ttk.Button(
                button_container,
                text="Reset",
                width=8,
                command=self._stop_processing
            )
            reset_button.pack(side=tk.RIGHT, padx=10)

            # Start button
            start_button = ttk.Button(
                button_container,
                text="Start",
                width=8,
                command=self._start_processing
            )
            start_button.pack(side=tk.RIGHT, padx=10)

            # Initialize ports list
            self._refresh_ports()

        except Exception as e:
            logging.error(f"Error creating Process Monitor page: {e}")
            messagebox.showerror("Error", "Failed to create Process Monitor page")

if __name__ == "__main__":
    root = tk.Tk()
    app = ShapeApp(root)
    root.mainloop()