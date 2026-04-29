# AI Model Test | Realtime @rasvet
import dxcam
import numpy as np
import win32gui
import win32con
import win32api
import ctypes
import time
from ultralytics import YOLO
from PIL import Image, ImageDraw, ImageFont


MODEL_PATH = "../best.pt"
OBJECT_NAME = "proto_enemy"
CONFIDENCE = 0.5
FPS = 70 

TEXT_SIZE = 16

model = YOLO(MODEL_PATH)

def get_color_from_confidence(confidence):
    """ Градация цвета рамки в зависимости от уверенности """
    RED_THRESHOLD = 0.2

    if confidence <= RED_THRESHOLD:
        return (0, 0, 255)

    normalized_conf = (confidence - RED_THRESHOLD) / (1.0 - RED_THRESHOLD)
    blue = int(255 * (1 - normalized_conf))
    green = int(255 * normalized_conf)
    
    return (0, green, blue)

class POINT(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_long),
        ("y", ctypes.c_long)
    ]

class SIZE(ctypes.Structure):
    _fields_ = [
        ("cx", ctypes.c_long),
        ("cy", ctypes.c_long)
    ]

class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]

def get_screen_size():
    user32 = ctypes.windll.user32
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)

class Overlay:
    def __init__(self, w, h):
        self.w = w
        self.h = h

        wc = win32gui.WNDCLASS()
        wc.lpfnWndProc = win32gui.DefWindowProc
        wc.lpszClassName = "OverlayWindow"
        try:
            win32gui.RegisterClass(wc)
        except:
            pass

        ex_style = (
            win32con.WS_EX_LAYERED |
            win32con.WS_EX_TOPMOST |
            win32con.WS_EX_TRANSPARENT |
            win32con.WS_EX_TOOLWINDOW |
            win32con.WS_EX_NOACTIVATE
        )

        self.hwnd = win32gui.CreateWindowEx(
            ex_style,
            "OverlayWindow",
            None,
            win32con.WS_POPUP,
            0, 0, w, h,
            None, None, None, None
        )

        win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE,
            win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE) | win32con.WS_EX_TRANSPARENT)

        win32gui.ShowWindow(self.hwnd, win32con.SW_SHOW)

        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32

    def clear_buffer(self):
        return np.zeros((self.h, self.w, 4), dtype=np.uint8)

    def draw_boxes_and_text(self, img, boxes):
        """ Рамка и текст """
        pil_img = Image.fromarray(img, 'RGBA')
        draw = ImageDraw.Draw(pil_img)
        
        try:
            font = ImageFont.truetype("arial.ttf", TEXT_SIZE)
        except:
            font = ImageFont.load_default()
        
        for box_data in boxes:
            x1, y1, x2, y2 = box_data['coords']
            conf = box_data['conf']
            color = box_data['color']
            
            color_rgba = color + (255,)
            
            for i in range(2):
                draw.rectangle(
                    [x1 - i, y1 - i, x2 + i, y2 + i], 
                    outline=color_rgba
                )
            
            text = f'{OBJECT_NAME} {conf}%'
            
            bbox = draw.textbbox((0, 0), text, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            
            text_x = x1
            text_y = y1 - text_height - 5
            
            if text_y < 0:
                text_y = y1 + 5
            
            padding = 3
            draw.rectangle(
                [
                    text_x - padding,
                    text_y - padding,
                    text_x + text_width + padding,
                    text_y + text_height + padding
                ],
                fill=(0, 0, 0, 180)
            )
            
            draw.text((text_x, text_y), text, font=font, fill=color_rgba)
        
        return np.array(pil_img)

    def render_buffer(self, img):
        bits = img.tobytes()

        hdc_screen = self.user32.GetDC(0)
        hdc_mem = self.gdi32.CreateCompatibleDC(hdc_screen)

        hbmp = self.gdi32.CreateBitmap(self.w, self.h, 1, 32, bits)
        self.gdi32.SelectObject(hdc_mem, hbmp)

        blend = BLENDFUNCTION(0, 0, 255, 1)

        pt_src = POINT(0, 0)
        pt_dst = POINT(0, 0)
        size = SIZE(self.w, self.h)

        self.user32.UpdateLayeredWindow(
            self.hwnd,
            hdc_screen,
            ctypes.byref(pt_dst),
            ctypes.byref(size),
            hdc_mem,
            ctypes.byref(pt_src),
            0,
            ctypes.byref(blend),
            2
        )

        self.gdi32.DeleteObject(hbmp)
        self.gdi32.DeleteDC(hdc_mem)
        self.user32.ReleaseDC(0, hdc_screen)

    def destroy(self):
        win32gui.DestroyWindow(self.hwnd)

def print_status(fps, detections_count, running_time):
    print(f"\r[+] FPS: {fps:.1f} | Detections: {detections_count} | Time: {running_time:.0f}s", end="")


def main():
    screen_w, screen_h = get_screen_size()
    print(f"Screen: {screen_w}x{screen_h}")
    
    camera = dxcam.create(output_color="BGR")
    camera.start(target_fps=FPS)
    
    overlay = Overlay(screen_w, screen_h)
    
    print("=" * 50)
    print(" AI Overlay Running")
    print(f" Model: {MODEL_PATH}")
    print(f" Target: {OBJECT_NAME}")
    print(f" Confidence: {CONFIDENCE}")
    print(f" Press ESC to exit")
    print("=" * 50)
    
    last_time = time.time()
    frame_count = 0
    fps = 0
    start_time = time.time()
    
    try:
        while True:
            if win32api.GetAsyncKeyState(win32con.VK_ESCAPE) & 0x8000:
                break
            
            frame = camera.get_latest_frame()
            if frame is None:
                continue
            
            buffer = overlay.clear_buffer()
            
            results = model(frame, verbose=False)[0]
            
            detected_boxes = []
            
            if results.boxes is not None:
                for box in results.boxes:
                    conf = float(box.conf)
                    if conf < CONFIDENCE:
                        continue
                    
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    color = get_color_from_confidence(conf)
                    
                    detected_boxes.append({
                        'coords': (x1, y1, x2, y2),
                        'conf': int(conf * 100),
                        'color': color
                    })
            
            if detected_boxes:
                buffer = overlay.draw_boxes_and_text(buffer, detected_boxes)
            
            overlay.render_buffer(buffer)
            
            frame_count += 1
            current_time = time.time()
            if current_time - last_time >= 1.0:
                fps = frame_count / (current_time - last_time)
                frame_count = 0
                last_time = current_time
                print_status(fps, len(detected_boxes), current_time - start_time)
            
            time.sleep(1 / FPS)
    
    except KeyboardInterrupt:
        pass
    finally:
        print("\n[+] Stopping...")
        camera.stop()
        overlay.destroy()
        print("[+] Overlay destroyed")
        print("[+] Done!")

if __name__ == "__main__":
    main()