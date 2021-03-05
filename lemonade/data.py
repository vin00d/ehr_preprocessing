# AUTOGENERATED! DO NOT EDIT! File to edit: 04_data.ipynb (unless otherwise specified).

__all__ = ['EHRDataSplits', 'LabelEHRData', 'EHRDataset', 'EHRData']

# Cell
from .preprocessing.clean import * #for GVs
from .preprocessing.transform import *
from fastai.imports import *
import copy

# Cell
class EHRDataSplits():
    '''Class to hold the PatientList splits; defaults to loading 0 to 20 years age span'''
    def __init__(self, path, age_start=0, age_stop=20, age_in_months=False):
        self.train, self.valid, self.test = self._load_splits(path, age_start, age_stop, age_in_months)

    def _load_splits(self, path, age_start, age_stop, age_in_months):
        '''Load splits of preprocessed `PatientList`s from persistent store using path'''
        train = PatientList.load(path, 'train', age_start, age_stop, age_in_months)
        valid = PatientList.load(path, 'valid', age_start, age_stop, age_in_months)
        test  = PatientList.load(path, 'test',  age_start, age_stop, age_in_months)
        return train, valid, test

    def get_splits(self):
        '''Return splits'''
        return self.train, self.valid, self.test

    def get_lengths(self):
        '''Return a dataframe with lengths (# of patients) of the splits (train, valid, test) and total'''
        lengths = [len(self.train), len(self.valid), len(self.test), len(self.train)+len(self.valid)+len(self.test)]
        return pd.DataFrame(lengths, index=['train','valid','test','total'], columns=['lengths'])

    def get_label_counts(self, labels):
        '''Get prevalence counts of labels in each split - returns a dataframe with counts for each split and total count'''
        counts = []
        for label in labels:
            train_count = [getattr(self.train[i],label) == 1 for i in range(len(self.train))].count(True)
            valid_count = [getattr(self.valid[i],label) == 1 for i in range(len(self.valid))].count(True)
            test_count  = [getattr(self.test[i],label) == 1 for i in range(len(self.test))].count(True)
            total_count = train_count+valid_count+test_count
            counts.append([train_count, valid_count, test_count, total_count])
        return pd.DataFrame(counts, index=labels, columns=['train','valid','test','total'])

    def get_pos_wts(self, labels):
        '''Get positive weights to be used in `nn.BCEWithLogitsLoss`'''
        pos_counts = self.get_label_counts(labels)
        neg_counts = self.get_lengths().transpose().values - pos_counts
        return round(neg_counts / pos_counts)

# Cell
class LabelEHRData():
    '''Class to hold labeled EHR data splits'''
    def __init__(self, train, valid, test, labels):
        '''Extracts y from patient object, each labelset a tuple of x,y: x=Patient object, y=tensor of conditions'''
        self.x_train, self.y_train = train, self._get_y(train, labels)
        self.x_valid, self.y_valid = valid, self._get_y(valid, labels)
        self.x_test,  self.y_test  = test , self._get_y(test , labels)

        self.train = self.x_train, self.y_train
        self.valid = self.x_valid, self.y_valid
        self.test  = self.x_test,  self.y_test

    def _get_y(self, ds, labels):
        '''Extract y from each patient object in ds and stack them - ds is dataset containing patient objects'''
        y = []
        for pt in ds:
            y.append( torch.FloatTensor(np.array([getattr(pt,label) for label in labels], dtype='float')) )
        return torch.stack(y)

# Cell
class EHRDataset(torch.utils.data.Dataset):
    '''Class to hold a single EHR dataset (holds a tuple of x and y) -- handles lazy vs full loading of dataset on GPU'''
    def __init__(self, x_labeled, y_labeled, lazy_load_gpu=True):
        '''If `lazy_load_gpu` is `False`, load entire dataset on GPU'''
        if lazy_load_gpu:
            self.x, self.y = x_labeled, y_labeled
            self.lazy = True
        else:
            self.x, self.y = [x.to_gpu() for x in x_labeled], y_labeled.to(DEVICE)
            self.lazy = False

    def __len__(self): return len(self.x)

    def _test_getitem(self, i): return self.x[i],self.y[i]

    def __getitem__(self, i):
        '''If lazy loading, return deep copy of patient object `i`, else entire dataset already on GPU - just return `i`'''
        if self.lazy:
            return copy.deepcopy(self.x[i]), self.y[i]
        else:
            return self.x[i], self.y[i]

# Cell
class EHRData:
    '''All encompassing class for EHR data - holds Splits, Labels, Datasets, DataLoaders and provides convenience fns for training and prediction'''
    def __init__(self, path, labels, age_start=0, age_stop=20, age_in_months=False, lazy_load_gpu=True):
        self.path, self.labels = path, labels
        self.age_start, self.age_stop, self.age_in_months = age_start, age_stop, age_in_months
        self.lazy_load_gpu = lazy_load_gpu

    def load_splits(self):
        '''Load data splits given dataset path'''
        self.splits = EHRDataSplits(self.path, self.age_start, self.age_stop, self.age_in_months)

    def label(self):
        '''Run labeler - i.e. extract y from patient objects'''
        self.labeled = LabelEHRData(*self.splits.get_splits(), self.labels)

    def create_datasets(self):
        '''Create `EHRDataset`s'''
        self.train_ds = EHRDataset(*self.labeled.train, self.lazy_load_gpu)
        self.valid_ds = EHRDataset(*self.labeled.valid, self.lazy_load_gpu)
        self.test_ds  = EHRDataset(*self.labeled.test, self.lazy_load_gpu)

    def ehr_collate(b):
        '''Custom collate function for use in `DataLoader`'''
        xs,ys = zip(*b)
        return xs, torch.stack(ys)

    def create_dls(self, bs, lazy, c_fn=ehr_collate, **kwargs):
        '''Create `DataLoader`s'''
        self.train_dl = DataLoader(self.train_ds, bs, shuffle=True, collate_fn=c_fn, pin_memory=lazy, **kwargs)
        self.valid_dl = DataLoader(self.valid_ds, bs*2, collate_fn=c_fn, pin_memory=lazy, **kwargs)
        self.test_dl  = DataLoader(self.test_ds,  bs*2, collate_fn=c_fn, pin_memory=lazy, **kwargs)

    def get_data(self, bs=64, num_workers=0):
        '''Convenience function - returns everything needed for training'''
        self.load_splits()
        self.label()
        self.create_datasets()
        self.create_dls(bs, self.lazy_load_gpu, num_workers=num_workers)

        pos_wts = self.splits.get_pos_wts(self.labels)
        train_pos_wts = torch.Tensor(pos_wts['train'].values)
        valid_pos_wts = torch.Tensor(pos_wts['valid'].values)
        return self.train_dl, self.valid_dl, train_pos_wts, valid_pos_wts

    def get_test_data(self, bs=64, num_workers=0):
        '''Convenience function - returns everything needed for prediction using test data'''
        self.load_splits()
        self.label()
        self.create_datasets()
        self.create_dls(bs, self.lazy_load_gpu, num_workers=num_workers)

        pos_wts = self.splits.get_pos_wts(self.labels)
        test_pos_wts = torch.Tensor(pos_wts['test'].values)
        return self.test_dl, test_pos_wts