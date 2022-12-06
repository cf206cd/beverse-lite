class Config:
    '''x:forward, y:left, z:up'''
    GRID_CONFIG = {
    #for 3D grid:x forward,y left,z up
    'base': {
        'xbound': [-51.2, 51.2, 0.8],
        'ybound': [-51.2, 51.2, 0.8],
        'zbound': [-10.0, 10.0, 20.0],
        'dbound': [1.0, 60.0, 1.0],
    },
    #for 2D gird:x right,y down
    'det': {
        'xbound': [-50.0, 50.0, 0.5],
        'ybound': [-50.0, 50.0, 0.5],
    },
    'seg': {
        'xbound': [-30.0, 30.0, 0.15],
        'ybound': [-15.0, 15.0, 0.15],
    }
    }

    MEAN = [0.485, 0.456, 0.406]
    STD = [0.229, 0.224, 0.225]

    INPUT_IMAGE_SIZE = (640,640)

    DEVICE = "cpu"
    EPOCH = 100
    
    BATCH_SIZE = 2
    LEARNING_RATE = 1e-3
    MOMENTUM = 0.99
    LR_SCHE_STEP_SIZE = 1000
    LR_SCHE_GAMMA = 0.1