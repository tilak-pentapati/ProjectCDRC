#!/usr/bin/env python
# coding: utf-8
import os
import os.path

import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.model_selection import train_test_split
from sklearn.model_selection import ShuffleSplit
from sklearn.metrics import r2_score, mean_squared_error
from math import sqrt
import lightgbm as lgb
import shap
import pickle
from sklearn.preprocessing import StandardScaler
from sklearn.inspection import PartialDependenceDisplay

import matplotlib.pyplot as plt
import matplotlib.cm as cm

from util import *
from repeated_cross_val import get_dataset_spatial_fold_splits, get_dataset_fold_splits
from lightGBM import train_LGB



def prepare_model_inputs(dataset,outcome_col, all_outcomes):
    
    labels = np.array(dataset[outcome_col])
    # Remove the labels from the features
    # axis 1 refers to the columns
    features= dataset.drop(all_outcomes, axis = 1)
    
    return features, labels


def LGB(x_train, y_train, x_val, y_val, x_test, y_test):

    # Define LightGBM parameters
    params = {
        'objective': 'regression',
        'metric': 'rmse',
    }

    # Train and evaluate model using cross-validation

    # Create LightGBM datasets
    train_data = lgb.Dataset(x_train, label=y_train)
    val_data = lgb.Dataset(x_val, label=y_val)

    # Train model with early stopping
    model = lgb.train(params, train_data, valid_sets=[val_data], early_stopping_rounds=10)

    train_r2 = r2_score(y_train, model.predict(x_train))
    val_r2 = r2_score(y_val, model.predict(x_val))
    test_r2 = r2_score(y_test, model.predict(x_test))

    print(f'Train R^2: {train_r2:.4f}')
    print(f'Validation R^2: {val_r2:.4f}')

    return model

def plot_individual_LSOAs(lsoa_id, dataset, shap_values, condition):
    # shap.summary_plot(np.array(shap_values), test_features, plot_type="bar")
    lsoa_index = dataset.index.get_loc(lsoa_id)
    shap.plots.waterfall(shap_values[lsoa_index], max_display=10, show=False)

    plt.title("SHAP for {} and {}".format(lsoa_id, condition))
    plt.tight_layout()
    plt.show()

def visualize_dependence_plot(shap_values, x_test, shap_results_base_dir, condition):
    width = 6.5
    # if condition == "diabetes":
    #     width = 3.3
    fig = plt.figure()
    shap.dependence_plot("rank(0)", shap_values.values, x_test, show=False)
    plt.gcf().set_size_inches(width, 4)
    plt.yticks(fontsize=8)
    plt.xticks(fontsize=8)

    plt.title("Dependence Plot for {} prescriptions".format(condition), fontsize=10)
    fig.tight_layout()
    plt.savefig(os.path.join(shap_results_base_dir, "PDP_{}.pdf".format(condition)), dpi=300)
    plt.close()


#latex article class has witdh of 397.484pt
def visualize_shap_values(shap_explainer, shap_results_base_dir, condition):
    width = 4
    # if condition == "diabetes":
    #     width = 3.3
    fig = plt.figure()
    shap.summary_plot(shap_explainer, show=False, max_display=15, color_bar=False, cmap="plasma")
    plt.gcf().set_size_inches(width, 4.5)
    plt.yticks(fontsize=8)
    plt.xticks(fontsize=8)
    # if condition != "diabetes":
    #color = shap.plots.colors.blue_rgb
    #cmap = shap.plots._utils.convert_color(color)
    m = cm.ScalarMappable(cmap="plasma")
    m.set_array([0, 1])
    cb = plt.colorbar(m, ticks=[0, 1], aspect=50)
    cb.set_ticklabels(["Low", "High"])
    cb.set_label("Feature value", size=10, labelpad=-2)
    cb.ax.tick_params(labelsize=8, length=0)
    cb.set_alpha(1)
    cb.outline.set_visible(False)

    plt.xlabel("SHAP", fontsize=10)
    plt.title("{} prescriptions".format(condition), fontsize=10)
    fig.tight_layout()
    plt.savefig(os.path.join(shap_results_base_dir, "shap_values_{}.png".format(condition)), dpi=300)
    plt.close()


def compute_feature_rank(shap_values_test_df, condition, feature_name="population density", results_dir=""):
    total_feature_importances = np.abs(shap_values_test_df).mean(0)
    feature_importance = pd.DataFrame(list(zip(shap_values_test_df.columns, total_feature_importances)),
                                      columns=['col_name', 'feature_importance_vals'])
    feature_importance.sort_values(by=['feature_importance_vals'], ascending=False, inplace=True)
    print(feature_importance.head())
    feature_rank_index = feature_importance.index[feature_importance['col_name'] == feature_name]

    print(condition, feature_name, feature_rank_index)

    feature_importance.to_csv(os.path.join(results_dir, "feature_importance_{}.csv".format(condition)))

def compute_shap_values(target_year, target_modalities, split="spatial", leave_in_region=None, leave_out_region=None):
    region_split = get_region_label(leave_in_region, leave_out_region)
    shap_results_base_dir = os.path.join(results_folder, "lightGBM", "SHAP", split, str(target_year),
                                         "_".join(target_modalities))
    if region_split is not None:
        shap_results_base_dir = "{}_{}".format(shap_results_base_dir, region_split)
    if not os.path.exists(shap_results_base_dir):
        os.makedirs(shap_results_base_dir)

    if split == "spatial":
        print("Disabling leave_in_region and leave_out_region for the spatial fold split")
        leave_in_region = None
        leave_out_region = None

    dataset = read_spatial_dataset(target_year, leave_in_region, leave_out_region)

    if split == "spatial":
        fold_splits = get_dataset_spatial_fold_splits(dataset, target_year, 1)
    else:
        fold_splits = get_dataset_fold_splits(dataset)

    fold_split = fold_splits[0]

    train_data = fold_split[0]
    val_data = fold_split[1]
    test_data = fold_split[2]

    for i, condition in enumerate(all_conditions):  # enumerate(all_conditions):
        med_condition = "o_{}_quantity_per_capita".format(condition)
        # Separate features and target variable
        x_train, y_train = extract_features_and_labels(train_data, med_condition, target_modalities,
                                                       columns_to_filter=filtered_columns, agg_age_columns=True)
        x_val, y_val = extract_features_and_labels(val_data, med_condition, target_modalities,
                                                   columns_to_filter=filtered_columns, agg_age_columns=True)
        x_test, y_test = extract_features_and_labels(test_data, med_condition, target_modalities,
                                                     columns_to_filter=filtered_columns, agg_age_columns=True)

        # normalize data
        scaler = StandardScaler()
        x_train_norm = scaler.fit_transform(x_train)
        x_val_norm = scaler.transform(x_val)
        x_test_norm = scaler.transform(x_test)

        model = train_LGB(x_train_norm, y_train, x_val_norm, y_val)
        predictions = model.predict(x_test_norm)

        # Calculating R2
        test_r2 = r2_score(y_test, predictions)
        print('Test R^2: {} for condition {}'.format(test_r2, med_condition))

        # Calculating RMSE
        test_rmse = sqrt(mean_squared_error(y_test, predictions))
        print('Test RMSE: {} for condition {}'.format(test_rmse, med_condition))

        predictions_results = pd.DataFrame({"ACTUAL": y_test, "PREDICTED": predictions}, index=x_test.index)
        predictions_results["DIFF"] = (predictions_results["ACTUAL"] - predictions_results["PREDICTED"]).pow(2)
        predictions_results.sort_values(by="DIFF", inplace=True)
        predictions_results.to_csv(os.path.join(shap_results_base_dir, "test_predictions_{}.csv".format(condition)))

        # Compute SHAP values for test set
        # SHAPLEY value interpretation:
        print("Initializing SHAP explainer for: {}".format(med_condition))
        explainer = shap.TreeExplainer(model, feature_names=x_train.columns)

        print("Computing SHAP values")
        shap_values_train = explainer(x_train_norm)
        shap_values_val = explainer(x_val_norm)
        shap_values_test = explainer(x_test_norm)

        print("Computing SHAP dependence plot")
        visualize_dependence_plot(shap_values_test, x_test, shap_results_base_dir, condition)

        shap_values_train_df = pd.DataFrame(shap_values_train.values, columns=x_train.columns, index=x_train.index)
        shap_values_val_df = pd.DataFrame(shap_values_val.values, columns=x_val.columns, index=x_val.index)
        shap_values_test_df = pd.DataFrame(shap_values_test.values, columns=x_test.columns, index=x_test.index)

        shap_values_train_df.to_csv(os.path.join(shap_results_base_dir, "shap_values_train_{}.csv".format(condition)))
        shap_values_val_df.to_csv(os.path.join(shap_results_base_dir, "shap_values_val_{}.csv".format(condition)))
        shap_values_test_df.to_csv(os.path.join(shap_results_base_dir, "shap_values_test_{}.csv".format(condition)))

        # if condition == "total":
        #     plot_individual_LSOAs("E01023500", val_data, shap_values_val, condition)
        #     plot_individual_LSOAs("E01014782", train_data, shap_values_train, condition)

        visualize_shap_values(shap_values_test,shap_results_base_dir, condition)
        compute_feature_rank(shap_values_test_df, condition, results_dir=shap_results_base_dir)


if __name__ == '__main__':

    target_year = 2020
    #compute_shap_values(target_year, ["sociodemographic", "environmental"])
    compute_shap_values(target_year, ["geo","sociodemographic", "environmental", "image"], split="random")

