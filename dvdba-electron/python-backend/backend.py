#!/usr/bin/env python3
"""
DVDBA Python Backend — communicates with Electron via stdin/stdout JSON.
"""
import sys, json, os, struct, threading, time, subprocess
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from dvdbc.codec import encode_frame, decode_frame
from dvdbc.container import muxer
from dvdbc.quality import psnr, ssim
from dvdbc.cli import rgb_to_yuv_from_rgb
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None


def send(msg):
    line = json.dumps(msg, default=str)
    sys.stdout.write(line + '\n')
    sys.stdout.flush()


running_tasks = {}
cancel_flags = {}


def handle_encode(msg):
    input_path = msg['input']
    output_path = msg['output']
    quality = float(msg.get('quality', 50))
    keyframe = int(msg.get('keyframe', 30))
    task_id = msg.get('taskId', 'encode')
    cancel_flags[task_id] = False

    try:
        cap = cv2.VideoCapture(input_path)
        w = int(cap.get(3)); h = int(cap.get(4))
        fps = cap.get(5); total = int(cap.get(7))
        if total <= 0: total = 100

        header = muxer.mux_header(w, h, fps, total, quality, keyframe)
        frames_data = []
        ref_y = None
        start = time.time()

        for i in range(total):
            if cancel_flags.get(task_id):
                send({'taskId': task_id, 'status': 'cancelled'})
                cap.release()
                return

            ret, frame = cap.read()
            if not ret: break
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            is_key = i % keyframe == 0
            fd, recon_y, _ = encode_frame(rgb, quality, None if is_key else ref_y)
            ref_y = recon_y
            frames_data.append(fd)

            if i % 5 == 0 or i == total - 1:
                elapsed = time.time() - start
                pct = int((i + 1) / total * 100)
                fps_proc = (i + 1) / elapsed if elapsed > 0 else 0
                send({
                    'taskId': task_id, 'status': 'progress',
                    'percent': pct,
                    'message': f'Frame {i+1}/{total} ({fps_proc:.1f} fps)',
                    'frames': i + 1, 'time': round(elapsed, 1)
                })

        cap.release()

        os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
        with open(output_path, 'wb') as f:
            f.write(header)
            for fd in frames_data:
                f.write(fd)

        elapsed = time.time() - start
        size = os.path.getsize(output_path)
        send({
            'taskId': task_id, 'status': 'done',
            'frames': len(frames_data), 'size': size,
            'time': round(elapsed, 1),
            'fps': round(len(frames_data) / elapsed, 1) if elapsed > 0 else 0
        })

    except Exception as e:
        send({'taskId': task_id, 'status': 'error', 'error': str(e)})


def handle_decode(msg):
    input_path = msg['input']
    output_path = msg['output']
    task_id = msg.get('taskId', 'decode')
    cancel_flags[task_id] = False

    try:
        with open(input_path, 'rb') as f:
            data = f.read()
        info = muxer.parse_header(data)

        if cv2 is None:
            send({'taskId': task_id, 'status': 'error', 'error': 'OpenCV not available'})
            return

        fourcc = cv2.VideoWriter_fourcc(*'mp4v')
        out = cv2.VideoWriter(output_path, fourcc, info['fps'],
                              (info['width'], info['height']))
        ref_y = None
        offset = muxer.HEADER_SIZE
        idx, total = 0, info['frame_count']

        while offset < len(data):
            if cancel_flags.get(task_id):
                out.release()
                send({'taskId': task_id, 'status': 'cancelled'})
                return

            rem = data[offset:]
            fsize = int.from_bytes(rem[1:5], 'big')
            rgb = decode_frame(rem[:5+fsize], info['width'], info['height'],
                               info['quality'], ref_y)
            yuv = rgb_to_yuv_from_rgb(rgb)
            ref_y = yuv[..., 0].astype(np.uint8)
            out.write(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
            offset += 5 + fsize
            idx += 1

            if idx % 10 == 0 or idx == total:
                pct = int(idx / total * 100) if total > 0 else 0
                send({
                    'taskId': task_id, 'status': 'progress',
                    'percent': pct, 'message': f'Frame {idx}/{total}'
                })

        out.release()
        send({'taskId': task_id, 'status': 'done', 'frames': idx})

    except Exception as e:
        send({'taskId': task_id, 'status': 'error', 'error': str(e)})


def handle_probe(msg):
    input_path = msg['input']
    task_id = msg.get('taskId', 'decode-probe')

    try:
        with open(input_path, 'rb') as f:
            hdr = f.read(muxer.HEADER_SIZE)
        info = muxer.parse_header(hdr)
        size = os.path.getsize(input_path)

        # Get first frame preview
        preview_b64 = None
        if cv2:
            with open(input_path, 'rb') as f:
                data = f.read()
            offset = muxer.HEADER_SIZE
            rem = data[offset:]
            fsize = int.from_bytes(rem[1:5], 'big')
            rgb = decode_frame(rem[:5+fsize], info['width'], info['height'],
                               info['quality'], None)
            # Convert to base64 for preview
            import base64
            from io import BytesIO
            from PIL import Image
            img = Image.fromarray(rgb)
            buf = BytesIO()
            img.save(buf, format='JPEG', quality=85)
            preview_b64 = base64.b64encode(buf.getvalue()).decode()

        send({
            'taskId': task_id, 'status': 'info',
            'info': {
                'width': info['width'], 'height': info['height'],
                'fps': info['fps'], 'frames': info['frame_count'],
                'quality': info['quality'], 'size': size
            },
            'preview': preview_b64
        })
    except Exception as e:
        send({'taskId': task_id, 'status': 'error', 'error': str(e)})


def handle_compare(msg):
    orig_path = msg['original']
    comp_path = msg['compressed']
    task_id = msg.get('taskId', 'compare')

    try:
        with open(comp_path, 'rb') as f:
            comp_data = f.read()
        info = muxer.parse_header(comp_data)

        cap = cv2.VideoCapture(orig_path)
        psnr_vals, ssim_vals = [], []
        ref_y, offset = None, muxer.HEADER_SIZE
        idx = 0

        while offset < len(comp_data):
            ret, frame = cap.read()
            if not ret: break
            orig_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rem = comp_data[offset:]
            fsize = int.from_bytes(rem[1:5], 'big')

            try:
                dec_rgb = decode_frame(rem[:5+fsize], info['width'],
                                       info['height'], info['quality'], ref_y)
            except:
                break

            yuv = rgb_to_yuv_from_rgb(dec_rgb)
            ref_y = yuv[..., 0].astype(np.uint8)
            psnr_vals.append(psnr(orig_rgb, dec_rgb))
            ssim_vals.append(ssim(orig_rgb, dec_rgb))
            offset += 5 + fsize
            idx += 1

            if idx % 5 == 0:
                send({
                    'taskId': task_id, 'status': 'progress',
                    'percent': int(idx / info['frame_count'] * 100),
                    'message': f'Comparing frame {idx}/{info["frame_count"]}'
                })

        cap.release()

        if psnr_vals:
            orig_sz = os.path.getsize(orig_path)
            comp_sz = os.path.getsize(comp_path)
            send({
                'taskId': task_id, 'status': 'done',
                'psnr': round(float(np.mean(psnr_vals)), 2),
                'ssim': round(float(np.mean(ssim_vals)), 4),
                'ratio': round(orig_sz / comp_sz, 2) if comp_sz > 0 else 0,
                'frames': idx,
                'origSize': orig_sz, 'compSize': comp_sz
            })
        else:
            send({'taskId': task_id, 'status': 'error', 'error': 'No frames compared'})

    except Exception as e:
        send({'taskId': task_id, 'status': 'error', 'error': str(e)})


def handle_cancel(msg):
    task_id = msg.get('taskId', 'encode')
    cancel_flags[task_id] = True


def handle_open_folder(msg):
    path = msg.get('path', '')
    if sys.platform == 'win32':
        os.startfile(path)
    elif sys.platform == 'darwin':
        subprocess.run(['open', path])
    else:
        subprocess.run(['xdg-open', path])


handlers = {
    'encode': handle_encode,
    'decode': handle_decode,
    'probe': handle_probe,
    'compare': handle_compare,
    'cancel': handle_cancel,
    'open-folder': handle_open_folder,
    'shutdown': lambda m: sys.exit(0),
}


def main():
    send({'status': 'ready', 'version': '1.0.0'})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            cmd = msg.get('cmd', '')
            handler = handlers.get(cmd)
            if handler:
                thread = threading.Thread(target=handler, args=(msg,), daemon=True)
                thread.start()
            else:
                send({'taskId': msg.get('taskId'), 'status': 'error',
                      'error': f'Unknown command: {cmd}'})
        except json.JSONDecodeError:
            send({'status': 'error', 'error': 'Invalid JSON'})
        except Exception as e:
            send({'status': 'error', 'error': str(e)})


if __name__ == '__main__':
    main()
