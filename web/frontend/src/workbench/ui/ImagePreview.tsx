import DownloadLink from '../../components/DownloadLink';
import {ArtifactPreview} from '../../components/ArtifactGallery';
import {Modal} from './common';
import type {ImageLink} from '../platform/links';

/** Reuse the same image renderer and history-aware modal as the rest of the host. */
export default function ImagePreview({image,close}:{image:ImageLink;close:()=>void}){
 return <Modal open title="查看图片" onClose={close}>
  <div className="artifact-stage"><ArtifactPreview key={image.url} artifact={{url:image.url,name:image.name,kind:'image'}} expanded/></div>
  <div className="artifact-footer"><span className="artifact-name">{image.name}</span><DownloadLink className="btn btn-sm" href={image.downloadUrl||image.url} download={image.name}>下载原图</DownloadLink></div>
 </Modal>;
}
