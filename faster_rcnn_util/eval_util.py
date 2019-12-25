#!/usr/bin/env python
# -*- coding: utf-8 -*-
#------------------------------------------------------
# @ File       : eval_util.py
# @ Description:  
# @ Author     : Bharath Hariharan and Alex Chung
# @ Contact    : yonganzhong@outlook.com
# @ License    : Copyright (c) 2017-2018
# @ Time       : 2019/12/22 AM 11:45
# @ Software   : PyCharm
#-------------------------------------------------------

import os
import numpy as np
import xml.etree.ElementTree as ET

from Faster_RCNN.faster_rcnn_util import cfgs

NAME_LABEL_MAP = cfgs.PASCAL_NAME_LABEL_MAP


def generate_cls_bbox(all_boxes, img_name_list):
    """

    :param all_boxes: is a list. each item reprensent the detections of a img.
                      the detections is a array. shape is [-1, 6]. [category, score, xmin, ymin, xmax, ymax]
                      Note that: if none detections in this img. that the detetions is : []
    :param img_name_list:
    :return:
    """
    cls_box_dict = {}
    for cls_name, cls_id in NAME_LABEL_MAP.items():
        cls_score_boxes = None
        if cls_id == 0:
            continue
        else:
            for index, img_name in enumerate(img_name_list):
                detection_per_img = all_boxes[index]
                detection_cls_per_img = detection_per_img[detection_per_img[:, 0].astype(np.int32) == cls_id]
                if detection_cls_per_img.shape[0] == 0: # this cls has none detections in this image
                    continue
                else:
                    img_index = np.array([[index] * detection_cls_per_img.shape[0]]).transpose()
                    cls_box_score_per_img = np.hstack((img_index, detection_cls_per_img[:, 1:]))
                if cls_score_boxes is None:
                    cls_score_boxes = cls_box_score_per_img
                else:
                    cls_score_boxes = np.vstack((cls_score_boxes, cls_box_score_per_img))
        cls_box_dict[cls_name] = cls_score_boxes

    return cls_box_dict

def parse_rec(filename):
  """
  Parse a PASCAL VOC xml file
  :param filename:
  :return:
  """
  tree = ET.parse(filename)
  objects = []
  for obj in tree.findall('object'):
    obj_struct = {}
    obj_struct['name'] = obj.find('name').text
    obj_struct['pose'] = obj.find('pose').text
    obj_struct['truncated'] = int(obj.find('truncated').text)
    obj_struct['difficult'] = int(obj.find('difficult').text)
    bbox = obj.find('bndbox')
    obj_struct['bbox'] = [int(bbox.find('xmin').text),
                          int(bbox.find('ymin').text),
                          int(bbox.find('xmax').text),
                          int(bbox.find('ymax').text)]
    objects.append(obj_struct)

  return objects

def voc_average_precision(recall, precision):
    """
    ap = voc_average_precision(rec, prec)
    Compute VOC AP given precision and recall.
    :param recall:
    :param precision:
    :return:
    """
    mean_recall = np.concatenate(([0.], recall, [1.]))
    mean_precision = np.concatenate(([0.], precision, [0.]))

    # compute the precision envelope(descend oder)
    for i in range(mean_precision.size, 0, -1):
        mean_precision[i-1] = np.maximum(mean_precision[i-1], mean_precision[i])
    # compare adjacent value of recall to calculate area under PR curve, look for points
    # where X axis (recall) changes value
    real_recall_indices = np.where(mean_recall[1:], mean_recall[:-1])[0]

    # compute approximate area of PR curve
    # # and sum (\Delta recall) * precision
    average_precision = np.sum((mean_recall[real_recall_indices+1] - mean_recall[real_recall_indices]) *
                               mean_precision[real_recall_indices + 1])

    return average_precision



def voc_eval(img_name_list, cls_boxes, annotation_path, cls_name, overlap_threshold=0.5, use_diff=False):
    """
    calculate  precision, recall and mAP per class
    :param detpath:
    :param annopath:
    :param test_imgid_list:
    :param cls_name:
    :param overlap_threshold:
    :param use_diff:
    :return:
    """
    # step 1 parse xml to get gtboxes
    recs = {} # xml info
    for index, img_name in enumerate(img_name_list):
        recs[img_name] = parse_rec(os.path.join(annotation_path, img_name + '.xml'))

    # step 2 get gtboxes for this class
    class_recs = {}
    num_pos = 0 # record all image non difficult bbox of class
    for img_name in img_name_list:
        object_class_per_img = [obj for obj in recs[img_name] if obj['name'] == cls_name]
        bbox_class_per_img = np.array([x['bbox']] for x in object_class_per_img)
        if use_diff:
            difficult = np.array([False for x in object_class_per_img]).astype(np.bool)
        else:
            difficult = np.array([x['difficult'] for x in object_class_per_img]).astype(np.bool)

        det = [False] * len(object_class_per_img)

        num_pos = num_pos + sum(~difficult) # ignore the difficult boxes

        class_recs[img_name] = {'bbox':bbox_class_per_img, # all the detect box
                                'difficult': difficult, # the detect box is difficult label
                                'detected': det} # det means that gtboxes has already been detected


    # step 3 operate detection data
    img_indices = cls_boxes[:, 0].astype(np.int).tolist()
    confidence = cls_boxes[:, 1]
    cls_bbox = cls_boxes[:, 2:]

    num_detect = len(img_indices) # num of detections. That, a line is a det_box.
    true_positive = np.zeros(num_detect)
    false_positive = np.zeros(num_detect)

    if cls_bbox.shape[0] > 0:  # if exist detect boxes
        # sort by confidence
        sorted_indices = np.argsort(-confidence)  # get indices by confidence descend oder
        sorted_scores = np.argsort(-confidence) # get scores by confidence descend oder

        sorted_bbox = cls_bbox[sorted_indices, :]
        img_indices = [img_indices[x] for x in sorted_indices] # restore img indices by sorted indices

        #  go down dets and mark TPs and FPs
        for d in range(num_detect):
            object_class_per_img = class_recs[img_name_list[img_indices[d]]] # img_name_list[img_indices[d] == img_name
            bbox = sorted_bbox[d, :].astype(np.float)
            overlap_max = -np.inf
            gt_bbox = object_class_per_img['bbox'].astype(float) #

            if gt_bbox.size > 0:
                # compute overlap
                # computer intersection and unionby the bbox(predict)
                # and all ground true boxes of the bbox corresponding images

                # step 1 compute intersection
                inter_min_x = np.maximum(gt_bbox[:, 0], bbox[0])
                inter_min_y = np.maximum(gt_bbox[:, 1], bbox[1])
                inter_max_x = np.minimum(gt_bbox[:, 2], bbox[2])
                inter_max_y = np.minimum(gt_bbox[:, 3], bbox[3])

                inter_w = np.maximum(inter_max_x - inter_min_x + 1., 0)
                inter_h = np.maximum(inter_max_y - inter_min_y + 1., 0)
                inter_area = inter_w * inter_h
                # step 2 computer union
                # union = bbox_area + gt_bbox_area - intersection_area
                union_area = ((bbox[2] - bbox[0] + 1.) * (bbox[3] + bbox[1] + 1.) + # bbox_area
                         (gt_bbox[:, 2] - gt_bbox[:, 0] + 1.) * (gt_bbox[:, 3] - gt_bbox[:, 1] + 1.) +
                         inter_area
                         )

                overlap = inter_area / union_area
                overlap_max = np.max(overlap)
                overlap_max_index = np.argmax(overlap)

                if overlap_max > overlap_threshold:
                    if not object_class_per_img['difficult'][overlap_max_index]:
                        if not object_class_per_img['detected'][overlap_max_index]: # if has not been detected
                            true_positive[d] = 1
                            object_class_per_img['detected'][overlap_max_index] = True  # change flag to detected
                        else:
                            false_positive[d] = 1
                    else:
                        false_positive[d] = 1

    # step 4 ger recall, precision and AP(Average Precision)
    # precision = true_positive / (true_positive + false_positive)
    # recall = true_positive / (true_positive + false_negative)

    true_positive = np.cumsum(true_positive)  # get true positive detect number of bbox(predict)
    false_positive = np.cumsum(false_positive) # get false positive detect number of bbox(predict)

    recall = true_positive / float(num_pos)
    # avoid divide by zero in case the first detection matches a difficult ground truth
    precision = true_positive / np.maximum((true_positive + false_positive), np.finfo(np.float64).eps)

    # get average precision
    average_precision = voc_average_precision(recall=recall,
                               precision=precision)

    return recall, precision, average_precision


def execute_eval(img_name_list, cls_box_dict, annotation_path):
    """
    execute evaluation
    :param img_name_list:
    :param cls_box_dict:
    :param annotation_path:
    :return:
    """
    AP_list = []
    for cls_name, cls_index in NAME_LABEL_MAP.items():
        if cls_index == 0:
            continue
        else:
            recall, precision, AP = voc_eval(img_name_list=img_name_list,
                                             cls_boxes=cls_box_dict[cls_name],
                                             annotation_path=annotation_path,
                                             cls_name=cls_name)
            AP_list += [AP]
            print("cls : {}|| Recall: {} || Precison: {}|| AP: {}".format(cls_name, recall[-1], precision[-1], AP))
    # get mAP of all classes
    mAP = np.mean(AP_list)

    return mAP




def voc_evaluate_detection(all_boxes, annotation_path, img_name_list):
    """

    :param all_boxes: is a list. each item represent the detections of a img.
                      The detections is a array. shape is [-1, 6]. [category, score, xmin, ymin, xmax, ymax]
                      Note that: if none detections in this img. that the detetions is : []
    :param annotation_path:
    :param image_list:
    :return:
    """
    img_id_list = [img_name.split('.')[0] for img_name in img_name_list]

    cls_box_dict = generate_cls_bbox(all_boxes=all_boxes, img_name_list=img_id_list)

    mAP = execute_eval(img_name_list=img_id_list,
                 cls_box_dict=cls_box_dict,
                 annotation_path=annotation_path)
    return mAP

if __name__ == "__main__":
    pass
