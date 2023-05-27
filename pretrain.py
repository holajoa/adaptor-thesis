import torch

from pytorch_lightning import Trainer, seed_everything

from dataset.dataset import MultimodalPretrainedEmbeddingsDataset
from models.adaptor import Adaptor, StreamingProgressBar
from models.configurations import TEXT_PRETRAINED, VISION_PRETRAINED
from utils.dataset_utils import torch2huggingface_dataset, get_dataloader

from math import ceil
import argparse 
import logging


def main(args):
    if args.vision_model not in VISION_PRETRAINED.keys():
        raise ValueError(f'Vision model {args.vision_model} not available.'
                         f'Choose from {list(VISION_PRETRAINED.keys())}')
        
    if args.text_model not in TEXT_PRETRAINED.keys():
        raise ValueError(f'Text model {args.text_model} not available.'
                         f'Choose from {list(TEXT_PRETRAINED.keys())}')
        
    vision_model_config = VISION_PRETRAINED[args.vision_model]
    args.vision_pretrained = vision_model_config['pretrained_weight']
    args.vision_model_type = vision_model_config['vision_model_type']
    args.vision_output_dim = vision_model_config['vision_output_dim']
    args.text_pretrained = TEXT_PRETRAINED[args.text_model]
    
    ### Define model
    model = Adaptor(
        vision_output_dim=args.vision_output_dim,
        projection_dim=args.projection_dim,
        num_hidden_layers=args.num_hidden_layers, 
        lr=args.lr, 
    )

    ### Load dataset
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    dataset_device = 'cpu' if args.num_workers > 0 else device
    train_dataset = MultimodalPretrainedEmbeddingsDataset(args.text_model, args.vision_model, 
                                                          split='train', num_of_samples=args.num_of_samples, 
                                                          device=dataset_device, shuffle=True, seed=args.seed)
    args.max_steps = ceil(len(train_dataset) / args.batch_size) * args.num_train_epochs
    print(f'Number of training samples used: {len(train_dataset)}')
    print(f'Total number of training steps: {args.max_steps}')

    train_dataset = torch2huggingface_dataset(train_dataset, streaming=False)
    train_dataset.with_format('torch')

    val_dataset = MultimodalPretrainedEmbeddingsDataset(args.text_model, args.vision_model, 
                                                        split='valid', num_of_samples=args.num_of_samples, 
                                                        device=dataset_device)
    val_dataset = torch2huggingface_dataset(val_dataset, streaming=False)
    val_dataset.with_format('torch')

    # Get dataloaders
    train_dataloader = get_dataloader(
        train_dataset, 
        batch_size=args.batch_size,
        num_workers=args.num_workers,
        collate_fn=None,
    )
    val_dataloader = get_dataloader(
        val_dataset, 
        batch_size=args.batch_size,
        num_workers=args.num_workers,
        collate_fn=None,
    )
    
    ### Training
    seed_everything(args.seed)
    trainer = Trainer(
        accelerator="gpu", 
        devices=args.n_gpu, 
        strategy="ddp", 
        # accelerator="cpu",
        max_epochs=args.num_train_epochs,
        # max_steps=args.max_steps,
        log_every_n_steps=100, 
        check_val_every_n_epoch=1, 
        default_root_dir=args.output_dir,
        callbacks=[StreamingProgressBar(total=args.max_steps//args.num_train_epochs)],
        enable_progress_bar=False, 
    )
    trainer.fit(model, train_dataloader, val_dataloader)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument('--vision_model', type=str, help='Choose from [resnet-ae, swin-base]')
    parser.add_argument('--text_model', type=str, 
                        help='Choose from [bert, biobert, pubmedbert, cxrbert, clinicalbert]')
    parser.add_argument('--num_of_samples', type=int, default=-1, help='number of samples to use')
    parser.add_argument('--batch_size', type=int, default=32)

    parser.add_argument('--force_rebuild_dataset', action='store_true', help='Whether to force rebuild dataset, if not can load pickled file if available')
    parser.add_argument('--num_workers', type=int, default=8)
    parser.add_argument('--data_pct', type=float, default=1.0, help='percentage of data to use')
    parser.add_argument('--crop_size', type=int, default=224)

    parser.add_argument('--num_hidden_layers', type=int, default=1, help='number of transformer layers to use in adaptor')
    parser.add_argument('--projection_dim', type=int, default=768, help='dimension of projection head')

    parser.add_argument('--lr', type=float, default=1e-4)
    parser.add_argument('--num_train_epochs', type=int, default=1)

    parser.add_argument('--output_dir', type=str, default='./results', help='path to save model')
    
    parser.add_argument('--n_gpu', type=int, default=2, help='number of gpus to use')
    parser.add_argument('--seed', type=int, default=1117)
    parser.add_argument('--local_rank', default=-1, type=int, help='node rank for distributed training')
    
    args = parser.parse_args()


    from time import gmtime, strftime

    log_fn = strftime("%Y-%m-%d_%H:%M:%S", gmtime())
    logging.basicConfig(filename=f'logs/train_from_embeds_{log_fn}.log', encoding='utf-8', level=logging.INFO)

    num_of_gpus = torch.cuda.device_count()
    logging.info(f"Number of available GPUs = {num_of_gpus}: "
                f"{', '.join([torch.cuda.get_device_properties(i).name for i in range(num_of_gpus)])}.")
    
    main(args)
    