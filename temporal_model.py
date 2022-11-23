import torch
import torch.nn as nn
from regnet import regnetx_002
from fpn import FPN
from lss_transform import LSSTransform
from grid_sampler import GridSampler
from det_head import CenterPointHead
from seg_head import VanillaSegmentHead
from temporal_module import TemporalModule
from future_prediction import FuturePrediction
from pred_head import PredictHead

grid_confs = {
'det':{
    'xbound': [-51.2, 51.2, 0.8],
    'ybound': [-51.2, 51.2, 0.8],
    'zbound': [-10.0, 10.0, 20.0],
    'dbound': [1.0, 60.0, 1.0],
},
'mot': {
    'xbound': [-50.0, 50.0, 0.5],
    'ybound': [-50.0, 50.0, 0.5],
    'zbound': [-10.0, 10.0, 20.0],
    'dbound': [1.0, 60.0, 1.0],
},
'seg': {
    'xbound': [-30.0, 30.0, 0.15],
    'ybound': [-15.0, 15.0, 0.15],
    'zbound': [-10.0, 10.0, 20.0],
    'dbound': [1.0, 60.0, 1.0],
}
}

device = torch.device("cuda:0")
x = torch.zeros(6,3,640,640).to(device)
rots = torch.zeros(1,6,3,3)
trans = torch.zeros(1,6,3)
intrins = torch.zeros(1,6,3,3)
post_rots = torch.zeros(1,6,3,3)
post_trans = torch.zeros(1,6,3)
class TemporalModel(nn.Module):
    def __init__(self,num_det_classes=10,num_seg_classes=10,num_images=6):
        super().__init__()
        self.image_encoder = regnetx_002()
        self.image_fpn = FPN(in_channels=[56,152,368],out_channels=64)
        self.lss_transformer = LSSTransform(input_dim=(640,640),numC_input=64,numC_trans=64,downsample=8)
        self.lss_transformer.set_geometry((1, 6, 41, 80, 80, 64),rots,trans,intrins,post_rots,post_trans)
        self.bev_encoder = regnetx_002(input_channel=64,out_indices=[2,3],replace_stride_with_dilation=[True,True,True,False])
        self.bev_fpn = FPN(in_channels=[152,368],out_channels=64,out_ids=[0])
        grid_conf = grid_confs['det']
        self.grid_samplers = {}
        for task,conf in grid_confs.items():
            self.grid_samplers[task] = GridSampler(grid_conf,conf)
        self.det_head = CenterPointHead(64,num_det_classes)
        self.seg_head = VanillaSegmentHead(64,num_seg_classes)
        self.num_images = num_images

    def forward(self,rots=None, trans=None, intrins=None, post_rots=None, post_trans=None,use_pre_geom=False):
        image_feature = self.image_encoder(x)
        image_fpn_feature = self.image_fpn(image_feature)[0]
        image_fpn_feature = image_fpn_feature.reshape(-1,self.num_images,*image_fpn_feature.shape[1:])
        lss_feature = self.lss_transformer(image_fpn_feature,rots,trans,intrins,post_rots,post_trans,use_pre_geom=use_pre_geom)
        bev_feature = self.bev_encoder(lss_feature)
        bev_fpn_feature = self.bev_fpn(bev_feature)[0]
        grid_cells = {}
        for task,grid_sampler in self.grid_samplers.items():
            grid_cells[task] = grid_sampler(bev_fpn_feature)
        det_res = self.det_head(grid_cells['det'])
        seg_res = self.seg_head(grid_cells['seg'])
        return det_res,seg_res

if __name__ == '__main__':
    for i in range(3):
        rots[:,:,i,i] = 1
        intrins[:,:,i,i] = 1
        post_rots[:,:,i,i] = 1
    net = Model().to(device)
    import time
    start = time.time()
    for i in range(100):
        det_res,seg_res = net(x,rots,trans,intrins,post_rots,post_trans)
    end = time.time()
    print("FPS without pre geom",100/(end-start))
    print([i.shape for i in det_res])
    print(seg_res.shape)
    start = time.time()
    for i in range(100):
        det_res,seg_res = net(x,use_pre_geom=True)
    end = time.time()
    print("FPS with pre geom",100/(end-start))
    print([i.shape for i in det_res])
    print(seg_res.shape)