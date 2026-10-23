"""YOLO11 exported runtime. No model download or system dependency changes."""
import ctypes
import time
import cv2
import numpy as np
from . import config

class TensorRT:
    def __init__(self):
        import tensorrt as trt
        self.logger=trt.Logger(trt.Logger.ERROR); self.runtime=trt.Runtime(self.logger)
        self.engine=self.runtime.deserialize_cuda_engine(config.ENGINE.read_bytes())
        if self.engine is None: raise RuntimeError('TensorRT engine 不兼容')
        self.context=self.engine.create_execution_context()
        self.cuda=ctypes.CDLL('/usr/local/cuda/lib64/libcudart.so.12')
        self.cuda.cudaMalloc.argtypes=[ctypes.POINTER(ctypes.c_void_p),ctypes.c_size_t]
        self.cuda.cudaMemcpy.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int]
        self.cuda.cudaFree.argtypes=[ctypes.c_void_p]
        self.buffers=[]; self.arrays=[]
        for i in range(self.engine.num_io_tensors):
            name=self.engine.get_tensor_name(i)
            arr=np.empty(tuple(self.engine.get_tensor_shape(name)),dtype=trt.nptype(self.engine.get_tensor_dtype(name)))
            ptr=ctypes.c_void_p(); self.check(self.cuda.cudaMalloc(ctypes.byref(ptr),arr.nbytes))
            self.buffers.append(ptr);self.arrays.append(arr)
        self.name='TensorRT 10.3 · FP16 · CUDA'
    @staticmethod
    def check(code):
        if code: raise RuntimeError(f'CUDA runtime error {code}')
    def forward(self,blob):
        x=np.ascontiguousarray(blob,dtype=self.arrays[0].dtype)
        self.check(self.cuda.cudaMemcpy(self.buffers[0],ctypes.c_void_p(x.ctypes.data),x.nbytes,1))
        if not self.context.execute_v2([p.value for p in self.buffers]): raise RuntimeError('TensorRT inference failed')
        y=self.arrays[1]
        self.check(self.cuda.cudaMemcpy(ctypes.c_void_p(y.ctypes.data),self.buffers[1],y.nbytes,2))
        return y.copy()
    def close(self):
        for p in self.buffers: self.cuda.cudaFree(p)
        self.buffers=[]; self.context=None; self.engine=None; self.runtime=None

class Detector:
    def __init__(self):
        self.fallback=None
        try: self.backend=TensorRT(); self.name=self.backend.name
        except Exception as exc:
            self.fallback=str(exc)
            self.backend=None; self.net=cv2.dnn.readNetFromONNX(str(config.ONNX))
            self.name='OpenCV DNN · CPU（降级）'
    def detect(self,frame):
        started=time.perf_counter(); h,w=frame.shape[:2]; scale=min(640/w,640/h)
        rw,rh=round(w*scale),round(h*scale); left=(640-rw)//2; top=(640-rh)//2
        image=np.full((640,640,3),114,np.uint8)
        image[top:top+rh,left:left+rw]=cv2.resize(frame,(rw,rh))
        blob=cv2.dnn.blobFromImage(image,1/255,(640,640),swapRB=True)
        if self.backend: output=self.backend.forward(blob)
        else: self.net.setInput(blob);output=self.net.forward()
        rows=output[0].T
        # Keep low-score person candidates for ByteTrack's second association pass.
        scores=rows[:,4]; mask=(scores>=0.10)&(rows[:,4:].argmax(axis=1)==0)
        rows=rows[mask]; scores=scores[mask]
        boxes=np.empty((len(rows),4),np.float32)
        boxes[:,0]=(rows[:,0]-rows[:,2]/2-left)/scale
        boxes[:,1]=(rows[:,1]-rows[:,3]/2-top)/scale
        boxes[:,2]=rows[:,2]/scale; boxes[:,3]=rows[:,3]/scale
        indices=cv2.dnn.NMSBoxes(boxes.tolist(),scores.tolist(),0.10,0.45)
        indices=np.asarray(indices,dtype=int).reshape(-1)
        boxes=boxes[indices]; scores=scores[indices]
        if len(boxes):
            boxes[:,2:]+=boxes[:,:2]
            boxes[:,[0,2]]=boxes[:,[0,2]].clip(0,w)
            boxes[:,[1,3]]=boxes[:,[1,3]].clip(0,h)
        return boxes,scores,(time.perf_counter()-started)*1000
    def close(self):
        if self.backend: self.backend.close()

class Tracker:
    def __init__(self,fps):
        import supervision as sv
        self.sv=sv; self.tracker=sv.ByteTrack(track_activation_threshold=0.25,frame_rate=round(fps),lost_track_buffer=30,minimum_consecutive_frames=2)
    def update(self,boxes,scores,w,h):
        tracks=self.tracker.update_with_detections(self.sv.Detections(xyxy=boxes,confidence=scores,class_id=np.zeros(len(boxes),dtype=int)))
        result=[]
        if tracks.tracker_id is None: return result
        for box,score,tid in zip(tracks.xyxy,tracks.confidence,tracks.tracker_id):
            result.append({'id':int(tid),'confidence':float(score),'box':[float(box[0]/w),float(box[1]/h),float(box[2]/w),float(box[3]/h)]})
        return result
