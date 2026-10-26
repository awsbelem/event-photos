import sys, numpy as np, torch, torch.nn as nn
sys.path.insert(0, ".")
def block(i, o, norm=False):
    l=[nn.Conv2d(i,o,3,stride=2,padding=1), nn.LeakyReLU(0.2)]
    if norm: l.append(nn.InstanceNorm2d(o, affine=True))
    return l
class Classifier(nn.Module):
    def __init__(self):
        super().__init__()
        self.model=nn.Sequential(nn.Upsample(size=(256,256),mode='bilinear'),
            nn.Conv2d(3,16,3,stride=2,padding=1), nn.LeakyReLU(0.2), nn.InstanceNorm2d(16,affine=True),
            *block(16,32,True),*block(32,64,True),*block(64,128,True),*block(128,128),nn.Dropout(0.5),nn.Conv2d(128,3,8,padding=0))
    def forward(self,x): return self.model(x)
c=Classifier(); c.load_state_dict(torch.load("pretrained_models/sRGB/classifier.pth",map_location="cpu")); c.eval()
c.model=c.model[1:]  # resize done by caller
torch.onnx.export(c, torch.rand(1,3,256,256), "/tmp/ext/lut_classifier.onnx", opset_version=13, dynamo=False)
luts=torch.load("pretrained_models/sRGB/LUTs.pth",map_location="cpu")
basis=np.stack([luts[k]["LUT"].numpy() for k in ("0","1","2")])
print(basis.shape, basis.dtype, basis[0].min(), basis[0].max())
np.save("/tmp/ext/lut_basis.npy", basis.astype(np.float32))
x=torch.rand(1,3,256,256); print("torch", c(x).squeeze().detach().numpy())
np.save("/tmp/ext/x.npy", x.numpy())
