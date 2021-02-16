# pip install transformers datasets sklearn numpy torch torchvision
# code adapted from:
# https://colab.research.google.com/drive/1ayU3ERpzeJ8fHFJoEBCVCklxvvgjEz_P?usp=sharing#scrollTo=xxcHlNP21An8
import torch
from classification_experimental.datasets_for_finetune import DATA_LOADERS, TaskDataset
from hackashop_datasets.load_data import train_dev_test
# from datasets import load_metric
from sklearn.metrics import f1_score, precision_score, recall_score, accuracy_score
from transformers import AutoModelForSequenceClassification, \
    TrainingArguments, Trainer, AutoTokenizer
from argparse import ArgumentParser
import numpy as np
from torch.utils.data import DataLoader, SequentialSampler
import torch.nn.functional as F
import pandas as pd

# metric = load_metric('glue', 'sst2')

# def compute_metrics(eval_pred):
#     predictions, labels = eval_pred
#     predictions = np.argmax(predictions, axis=1)
#     return metric.compute(predictions=predictions, references=labels)

def compute_metrics(eval_pred):
    predictions, labels = eval_pred
    predictions = np.argmax(predictions, axis=1)
    f1 = f1_score(labels, predictions)
    pre = precision_score(labels, predictions)
    rec = recall_score(labels, predictions)
    acc = accuracy_score(labels, predictions)
    return {'acc': acc, 'rec': rec, 'f1': f1, 'pre': pre}

def trainer(args):
    random_seed = args.random_seed
    task_name = args.task_name
    data, labels = DATA_LOADERS[args.dataset]()
    pretrained_model = args.pretrained_model
    lr = args.lr
    max_len = args.max_len

    data_splits = train_dev_test(data, labels, random_seed)
    task_clf = TaskDataset
    train_dataset = task_clf(texts=data_splits['train'][0], 
                             labels=data_splits['train'][1], 
                             max_len=max_len,
                             tokenizer=pretrained_model)
    val_dataset = task_clf(texts=data_splits['dev'][0], 
                           labels=data_splits['dev'][1], 
                           max_len=max_len,
                           tokenizer=pretrained_model)

    # fine-tune/train BERT model for classification
    model = AutoModelForSequenceClassification.from_pretrained(
        pretrained_model, num_labels=args.num_label)

    model_name = f"{pretrained_model}_{random_seed}_{task_name}_{lr}_{max_len}"

    training_args = TrainingArguments(
        model_name,
        evaluation_strategy="epoch",
        learning_rate=lr,
        per_device_train_batch_size=args.per_device_train_batch_size,
        per_device_eval_batch_size=args.per_device_eval_batch_size,
        num_train_epochs=args.epochs,
        weight_decay=args.weight_decay,
        do_train=True,
        do_eval=True,
        load_best_model_at_end=True,
        metric_for_best_model='accuracy',
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        compute_metrics=compute_metrics,
    )

    print(f'Finetuning the model {model_name}')
    trainer.train()

    print(f'Evaluating the model {model_name}')
    eval_results = trainer.evaluate()
    print(f'Eval results \n{eval_results}')

    trainer.save_model(output_dir=model_name)
    print(f'Saved the model {model_name}')


def predict(args):
    tokenizer = args.pretrained_model
    max_len = args.max_len
    dataset = args.dataset
    fine_tuned_model = args.finetuned_model
    device = torch.device('cuda') if args.use_gpu else torch.device('cpu')

    texts, labels = DATA_LOADERS[dataset]()
    results = predict_fn(device, fine_tuned_model, max_len, texts, tokenizer)

    results = pd.DataFrame(results)
    results.to_csv(args.save_results)


def predict_fn(device, fine_tuned_model, max_len, texts, tokenizer):
    '''
    device: torch.device('cuda') or torch.device('cpu')
    fine_tuned_model: directory of fine tuned model
    max_len: use the length that had been used for fine-tuning, generally 128 since the texts are short
    texts: array of strings from data loaders
    tokenizer: pretrained model name for the tokenizer

    the function returns array of dictionary containing labels (0 or 1) and probabilities of assigned label
    '''
    model = AutoModelForSequenceClassification.from_pretrained(fine_tuned_model)
    dataset = TaskDataset(texts=texts, labels=None, max_len=max_len,
                          tokenizer=tokenizer)
    data_loader = DataLoader(dataset, sampler=SequentialSampler(dataset), batch_size=1)
    model.eval()
    model.to(device)

    results = []
    with torch.no_grad():
        for batch in data_loader:
            input_ids = batch['input_ids'].to(device)
            token_type_ids = batch['token_type_ids'].to(device)
            attention_mask = batch['attention_mask'].to(device)
            outputs = model(input_ids, token_type_ids=token_type_ids,
                            attention_mask=attention_mask)
            logits = outputs.logits
            probs = torch.max(F.softmax(logits, dim=1)).cpu().detach().numpy().item()
            label = torch.argmax(logits).cpu().detach().numpy().item()
            results.append({'probs': probs,
                            'label': label
                            })
    return results


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument('--dataset', type=str)
    # parser.add_argument('--dataset_path', type=str)
    parser.add_argument('--task_name', type=str)
    parser.add_argument('--random_seed', type=int)
    parser.add_argument('--pretrained_model', choices=['EMBEDDIA/crosloengual-bert'])
    parser.add_argument('--finetuned_model')
    parser.add_argument('--max_len', type=int)
    parser.add_argument('--num_label', type=int)
    parser.add_argument('--epochs', type=int)
    parser.add_argument('--label_name', type=str)
    parser.add_argument('--fine_tune', action='store_true')
    parser.add_argument('--prediction', action='store_true')
    parser.add_argument('--use_gpu', action='store_true')
    parser.add_argument('--lr', type=float)
    parser.add_argument('--per_device_train_batch_size', type=int)
    parser.add_argument('--per_device_eval_batch_size', type=int)
    parser.add_argument('--weight_decay', type=float)
    parser.add_argument('--nosplit', action='store_true')
    parser.add_argument('--save_results', type=str)
    args = parser.parse_args()

    if args.fine_tune:
        trainer(args)

    if args.prediction:
        predict(args)
